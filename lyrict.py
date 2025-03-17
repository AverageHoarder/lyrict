import os
import sys
import re
import subprocess
import shutil
import getpass
import argparse
from time import sleep
from tqdm import tqdm
from datetime import timedelta
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT, Encoding, TIT2, TPE1, TALB, TCOM, TEXT
from mutagen.id3._frames import TXXX
from mutagen.id3._util import ID3NoHeaderError
from collections import defaultdict

################################# MP3TAG CONFIG ######################################

# Name of the mp3tag action used to import synced lyrics from external .lrc files
import_synced_name = "LRC#Import Synced Lyrics From Filename.lrc"
# Tag to which the synced lyrics are saved in mp3tag
import_synced_tag = "LYRICS"

# Name of the mp3tag action used to import unsynced lyrics from external .txt files
import_unsynced_name = "LRC#Import Unsynced Lyrics From Filename.txt"
# Tag to which the unsynced lyrics are saved in mp3tag
import_unsynced_tag = "UNSYNCEDLYRICS"

# Name of the mp3tag action used to copy existing embedded lyrics to new tags with _BU appended, default: LYRICS_BU and UNSYNCEDLYRICS_BU
tag_backup_name = "LRC#Backup Embedded Lyrics"

# Name of the mp3tag action used to remove the backed up tags created with lyrics_backup, default: LYRICS_BU and SYLT_BU
remove_backup_name = "LRC#Remove Lyrics Backup"

################################ DO NOT TOUCH ########################################
# Parse arguments and fill variables to be passed to the main function
def parse_arguments():
    def dir_path(path):
        if os.path.isdir(path):
            return path
        else:
            raise argparse.ArgumentTypeError(f"readable_dir:{path} is not a valid path")
        
    parser = argparse.ArgumentParser(description='''Test .lrc and .txt lyrics for broken links, embed synced and unsynced lyrics into tags,
extract them from tags to files or populate the tags of external lyrics based on the tags of linked files.''')
    parser.add_argument('-d', '--directory',
                        help='test, import, mp3tag, tag_external: The directory to scan for .lrc and .txt files. export: Directory to scan for music files.',
                        type=dir_path, default=".", const=".", nargs="?")
    parser.add_argument('--delete', action='store_true',
                        help=f'''Import: After successful import, deletes external .lrc and .txt files from disk.
Export: After successful export, deletes LYRICS, SYLT and USLT tags from mp3 files and LYRICS and UNSYNCEDLYRICS tags from flac files.''')     
    parser.add_argument('-e', '--extensions',
                        help='''Test, Import, mp3tag: List of song extensions the script will look for, default: flac and mp3. 
Export: Song extensions that will be scanned for embedded lyrics, default flac and mp3''',
                        nargs='+', default=["flac", "mp3"])
    parser.add_argument('-l', '--log', action='count',
                        help='''Test, mp3tag: Log filepaths (lyric and music extension) to "lyrict_results.log". 
"-ll" logs each filetype separately (lrc_flac.log, txt_mp3.log...) instead.
Import, Export: log embedding/exporting results to "lyrict_import_results"/"lyrict_export_results"''')
    parser.add_argument('--log_path',
                        help='The directory to save logs to when used with -l or -ll, defaults to "."',
                        type=dir_path, default=".", const=".", nargs="?")
    parser.add_argument('-m', choices=['export', 'import', 'mp3tag', 'test', 'tag_external'], required=True,
                        help="""Mode, use 'test' to only log linked/unlinked songs to console or to file(s) when used with -l or -ll.
Use 'mp3tag' to embed external lyrics (.txt/.lrc) in audio tags via mp3tag.
Use 'import' to embed external lyrics (.txt/.lrc) in audio tags via mutagen.
Use 'export' to export embedded tags to external files (.lrc/.txt) via mutagen.
Use 'tag_external' to rewrite existing .lrc/.txt files and populate/update tag information like [ar:artist] at the start of the file.
""")
    parser.add_argument('-o', '--overwrite', action='store_true',
                        help='''mp3tag: Overwrite/recreate the mp3tag actions to reflect changes made in the config section.
Import: Purge and overwrite existing embedded lyrics tags (LYRICS/UNSYNCEDLYRICS/SYLT/USLT)
Export: Overwrite the content of existing .lrc/.txt files.''')
    parser.add_argument('-p', '--progress', action='store_true',
                        help='Show progress bars. Useful for huge directories. Requires tqdm, use "pip3 install tqdm" to install it.')       
    parser.add_argument('-s', '--single_folder', action='store_true',
                        help='Test, Import, mp3tag: Only scans a single folder for .lrc and .txt files, no subdirectories. Export: Only scans a single folder for music files.')
    parser.add_argument('--standardize', choices=['keep', 'force.xx', 'force.xxx'], default='keep', const='keep', nargs="?",
                        help=f'''Import/Export/tag external: standardize and fix timestamps of synced lyrics.
Use 'keep' or leave empty to retain existing timestamp formats and only fix mistakes like >59 minutes or >59 seconds.
Use 'force.xx' to force all existing timestamps into `[hh:mm:ss.xx]` or `[mm:ss.xx]` format.
Use 'force.xxx' to force all existing timestamps into `[hh:mm:ss.xxx]` or `[mm:ss.xxx]` format''')

    args: argparse.Namespace = parser.parse_args()

    setattr(args, "log_to_disk", False)
    setattr(args, "separate_logs", False)
    if args.log == 1:
        setattr(args, "log_to_disk", True)
    elif args.log == 2:
        setattr(args, "log_to_disk", True)
        setattr(args, "separate_logs", True)

    setattr(args, "export_mode", False)
    setattr(args, "import_mode", False)
    setattr(args, "test_mode", False)
    setattr(args, "mp3tag_mode", False)
    setattr(args, "tag_external_mode", False)

    if args.m == 'export':
        setattr(args, "export_mode", True)
    elif args.m == 'import':
        setattr(args, "import_mode", True)
    elif args.m == 'test':
        setattr(args, "test_mode", True)
    elif args.m == 'mp3tag':
        setattr(args, "mp3tag_mode", True)
    elif args.m == 'tag_external':
        setattr(args, "tag_external_mode", True)

    return args

########################################## SHARED ############################################
# Find all .lrc and .txt files in the directory specified with -d, recursively if not called with -s, --single
def find_lyrics_files(directory, single_folder, progress):
    lyrics_files = defaultdict(list)
    txt_pattern = re.compile(r'^\d{2,3}\s') # Pattern to filter .txt files, default filters for names starting with 2 or 3 digits and a space, like "01 Hello.flac"

    if not single_folder:
        with tqdm(desc="searching", unit=" files", disable=not progress, ncols=100) as pbar:
            lrc_count = 0
            txt_count = 0
            for root, dirs, files in os.walk(directory):
                for file in files:
                    pbar.update(1)
                    if file.endswith(".lrc"):
                        lyrics_files["lrc"].append(os.path.join(os.path.abspath(root), file))
                        lrc_count += 1
                        pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})
                    elif file.endswith(".txt") and re.match(txt_pattern, file):
                        lyrics_files["txt"].append(os.path.join(os.path.abspath(root), file))
                        txt_count += 1
                        pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})
    else:
        with tqdm(desc="searching", unit=" files", disable=not progress, ncols=100) as pbar:
            lrc_count = 0
            txt_count = 0
            for file in os.listdir(directory):
                if file.endswith(".lrc"):
                    lyrics_files["lrc"].append(os.path.join(os.path.abspath(root), file))
                    lrc_count += 1
                    pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})              
                elif file.endswith(".txt")and re.match(txt_pattern, file):
                    lyrics_files["txt"].append(os.path.join(os.path.abspath(root), file))
                    txt_count += 1
                    pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})

    if not lyrics_files:
        print("No external lyrics (.lrc/.txt) found, closing in 5 seconds.")
        sleep(5)
        sys.exit()
    else:
        return lyrics_files

# Find matching songs from -e, --extensions list for .lrc and .txt files
def find_matches(lyrics_files, extensions, progress):
    match_categories = {}
    for lyrics_type, paths in lyrics_files.items():
        match_categories[lyrics_type] = defaultdict(list)
        with tqdm(total = len(paths), desc= f"finding {lyrics_type} matches", unit=f" {lyrics_type} files", disable=not progress, ncols=100) as pbar:
            for song in paths:
                hits = False
                for ext in extensions:
                    song_path = os.path.splitext(song)[0] + f'.{ext}'
                    if os.path.isfile(song_path):
                        match_categories[lyrics_type][ext].append(song_path)
                        hits = True
                        pbar.update(1)
                if not hits:
                    match_categories[lyrics_type]["unlinked"].append(song)
    return match_categories

##################################### IMPORT MP3TAG #############################################
# Open only songs with matching lyrics in mp3tag via CLI
def add_to_mp3tag(match_categories):
    # Create a temporary .m3u8 file containing all songs with linked lyrics
    file_paths = set()  # Use a set to remove duplicates

    # Collect all file paths
    for audio_types in match_categories.values():
        for file_list in audio_types.values():
            file_paths.update(file_list)

    # Sort file paths
    sorted_paths = sorted(file_paths)

    # Write to .m3u8 file
    with open("lyrict_temp.m3u8", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")  # M3U8 header
        for file in sorted_paths:
            f.write(f"{file}\n")
    try:
        print("Waiting for Mp3tag to close before removing lyrict_temp.m3u8.")
        subprocess.run(["mp3tag", "/fn:lyrict_temp.m3u8"])
    except subprocess.CalledProcessError:
        print(f"Error while opening lyrict_temp.m3u8 in Mp3tag.")
    try:
        os.remove("lyrict_temp.m3u8")
    except:
        print("Could not remove lyrict_temp.m3u8.")

# Check if mp3tag is on PATH and instruct how to add it if it isn't (Windows only)
def mp3tag_on_path():
    if shutil.which("mp3tag") is None and sys.platform == "win32":
        choice = input("mp3tag is not on PATH, open environment variable settings in Windows to add it? (y/n): ")
        if choice == "y":
            print(f"""
    Step 1: Under 'User variables for {getpass.getuser()}' select 'Path' and either double click it or click on 'Edit...'
    Step 2: Check if a path to Mp3tag is among the entries, if not, click on 'New' and paste:
            C:\\Program Files\\Mp3tag
            If you have mp3tag installed in a different directory, add the path to that instead.
            Note: You can also add the folder that contains this script to PATH in the same way.
    Step 3: Once that is done, re-run this script.""")
            try:
                subprocess.run(["rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"])
            except subprocess.CalledProcessError:
                print(f"Error opening environment variable settings.")
            sys.exit()
        else:
            print("Exiting.")
            sys.exit()
    elif shutil.which("mp3tag") is None:
        print("mp3tag is not on PATH, add it and try again. Closing in 5 seconds.")
        sleep(5)
        sys.exit()
    else:
        return

# Create mp3tag actions to backup existing embedded lyrics, import external lyrics and delete the lyrics backups
def mp3tag_create_actions(action_folder, overwrite):
    class Mp3tagAction:
        action_list = []
        def __init__(self, name, content):
            self.name = name
            self.path = os.path.join(action_folder + name + ".mta")
            self.content = content
            Mp3tagAction.action_list.append(self)
        def create(self):
            choice = ""
            if os.path.isfile(self.path) and not overwrite:
                return
            if not overwrite:
                choice = input(f"Create a mp3tag action called '{self.name}' in:\n{action_folder}? (y/n): ")
            if choice == "y" or overwrite:
                try:
                    with open(self.path, "w", encoding="utf-8") as action:
                        action.write(self.content)
                except PermissionError:
                    print(f"{self.path}.mta cannot be created, ensure that you have write permissions and try again.")
                    sys.exit(1)
                print(f"{self.path} saved.")
            else:
                return
                
    backup_tags = f"{import_synced_tag}_BU;{import_unsynced_tag}_BU"
    backup_tag_synced = f"{import_synced_tag}_BU"
    backup_tag_unsynced = f"{import_unsynced_tag}_BU"

    backup_action = Mp3tagAction(tag_backup_name, f"[#0]\nT=5\n1={import_synced_tag}\nF={backup_tag_synced}\n\n[#1]\nT=5\n1={import_unsynced_tag}\nF={backup_tag_unsynced}\n")
    delete_backup_action = Mp3tagAction(remove_backup_name, f"[#0]\nT=9\nF={backup_tags}\n")
    import_synced_action = Mp3tagAction(import_synced_name, f"[#0]\nT=14\nF={import_synced_tag}\n1=%_filename%.lrc\n")
    import_unsynced_action = Mp3tagAction(import_unsynced_name, f"[#0]\nT=14\nF={import_unsynced_tag}\n1=%_filename%.txt\n")
    
    [action.create() for action in Mp3tagAction.action_list]

# Open songs with both types of matching lyrics (synced/unsynced) in mp3tag
def mp3tag_open_songs(match_categories, action_folder, overwrite):
    errors = False
    for lyrics_type, audio_types in match_categories.items():
        if "unlinked" in audio_types:
            print(f"{lyrics_type.upper()} files without linked songs found:")
            for path in match_categories[lyrics_type]["unlinked"]:
                print(path)
            errors = True
    if errors:
        # Remove 'unlinked' keys from match_categories and remove empty categories.
        cleaned_match_categories = {
        lyrics_type: {k: v for k, v in audio_types.items() if k != "unlinked"}
        for lyrics_type, audio_types in match_categories.items()
        if any(k != "unlinked" for k in audio_types)
        }
        if cleaned_match_categories:
            choice = input(f"Open songs with external lyrics in Mp3tag anyhow? (y/n): ")
            if choice == "y":
                mp3tag_on_path()
                if not os.path.isdir(action_folder):
                    print(f"{action_folder} not found, skipping action creation.")
                else:
                    mp3tag_create_actions(action_folder=action_folder, overwrite=overwrite)
                add_to_mp3tag(match_categories=cleaned_match_categories)
        else:
            print("No linked songs found. Exiting in 1 second.")
            sleep(1)
            sys.exit()
    else:
        mp3tag_on_path()
        if not os.path.isdir(action_folder):
            print(f"{action_folder} not found, skipping action creation.")
        else:
            mp3tag_create_actions(action_folder=action_folder, overwrite=overwrite)
        add_to_mp3tag(match_categories=match_categories)

# Log found lrc paths to disk, grouped by extension and if there is a matching song
def write_log(match_categories, separate_logs, log_path):
    if not os.access(log_path, os.W_OK | os.X_OK):
        print("Cannot write log file(s) to current directory. Ensure that you have write permission. Skipping log creation.")
        return
    if not separate_logs:
        with open(os.path.join(log_path, "lyrict_results.log"), "w", encoding="utf8") as log:
            for lyrics_filetype, audio_types in match_categories.items():
                log.write(f"{lyrics_filetype.upper()}:\n")
                for audio_type in audio_types:
                    log.write(f"{audio_type}:\n")
                    for path in match_categories[lyrics_filetype][audio_type]:
                        log.write(f"{path}\n")
                    log.write("\n")
                log.write("\n")
    else:
        for lyrics_filetype, audio_types in match_categories.items():
            for audio_type in audio_types:
                with open(os.path.join(log_path, f"lyrict_{lyrics_filetype}_{audio_type}.log"), "w", encoding="utf8") as log:
                    for path in match_categories[lyrics_filetype][audio_type]:
                        log.write(f"{path}\n")

#################################### IMPORT MUTAGEN ########################################
def read_lyrics(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def parse_lrc_to_sylt(lyrics):
    sylt_lyrics = []
    language_pattern = re.compile(r'^\[la: *(\w{2,3})\]$', re.IGNORECASE | re.MULTILINE)
    offset_pattern = re.compile(r'^\[offset: *([+-]\d+)\]$', re.IGNORECASE | re.MULTILINE)
    timestamp_pattern = re.compile(r'^\[(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?\] *(?!(?:.*<\d{1,3}:|\[\d{1,3}:))(.*)$')
    mutli_timestamp_check_pattern = re.compile(r'^(?:\[(?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?\] *){2,}.*$')
    multi_timestamp_pattern = re.compile(r'(\[(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?\])')
    multi_text_pattern = re.compile(r'^(?:\[(?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?\])+ *(.*)$')
    lines = lyrics.splitlines()
    omitted_lines = []
    language = ""
    offset = 0
    
    # Determine language and offset
    match_lang = language_pattern.search(lyrics)
    if match_lang:
        language = match_lang.group(1)
    else:
        language = "eng" # Default to English if no language tag was detected in the .lrc file
    match_offset = offset_pattern.search(lyrics)
    if match_offset:
            offset = int(match_offset.group(1))

    for index, line in enumerate(lines):
        if timestamp_pattern.match(line): # Append lines that follow a [timestamp]lyrics pattern.
            match = timestamp_pattern.match(line)
            hours, minutes, seconds, milliseconds, text = match.groups()
            hours = int(hours) if hours else 0
            minutes = int(minutes)
            seconds = int(seconds)
            milliseconds = int(milliseconds.ljust(3, '0')) if milliseconds else 0 # Convert to milliseconds 
            timestamp = (hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds + offset)
            if timestamp >= 0:
                sylt_lyrics.append((text.strip(), timestamp))
        elif mutli_timestamp_check_pattern.match(line): # Detect repeated lines [mm:ss.xxx][mm:ss.xxx]...
            timestamps = re.findall(multi_timestamp_pattern, line)
            text = re.match(multi_text_pattern, line)
            text = text.group(1).strip() if text else ""
            for timestamp in timestamps:
                hours = match[1]
                minutes = int(match[2])
                seconds = int(match[3])
                milliseconds = match[4]
                hours = int(hours) if hours else 0
                milliseconds = int(milliseconds.ljust(3, '0')) if milliseconds else 0 # Convert to milliseconds
                sylt_timestamp = (hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds + offset)
                if sylt_timestamp > 0:
                    sylt_lyrics.append((text, sylt_timestamp))
        else:
            omitted_lines.append(f"{index + 1} {line}")

    return language, sorted(sylt_lyrics, key=lambda x: x[1]), omitted_lines

def embed_lyrics_flac(flac_file, lyrics=None, unsynced_lyrics=None, standardize=False, overwrite=False, results=None):
    audio = FLAC(flac_file)
    changed = False
    if not 'LYRICS' in audio or overwrite: # Embed if lyrics are not already embedded or when overwrite is True
        if lyrics:
            if standardize:
                lyrics = standardize_timestamps(lyrics, standardize)
            audio['LYRICS'] = lyrics
            changed = True
    if not 'UNSYNCEDLYRICS' in audio or overwrite: # Embed if lyrics are not already embedded or when overwrite is True
        if unsynced_lyrics:
            audio['UNSYNCEDLYRICS'] = unsynced_lyrics
            changed = True
    if changed:
        audio.save()
        results["saved"].append(flac_file)
    else:
        results["skipped"].append(flac_file)

def embed_lyrics_mp3(mp3_file, lyrics=None, unsynced_lyrics=None, overwrite=False, results=None):
    try:
        audio = MP3(mp3_file, ID3=ID3)
    except ID3NoHeaderError:
        audio = MP3(mp3_file)
        audio.add_tags()
    changed = False

    # SYLT frame
    if not any(isinstance(frame, SYLT) for frame in audio.tags.values()) or overwrite: # Embed if lyrics are not already embedded or when overwrite is True
        if lyrics:
            if overwrite:
                audio.tags.delall('SYLT') # delete existing SYLT frames to avoid duplicates
            language, sylt_lyrics, omitted_lines = parse_lrc_to_sylt(lyrics)
            audio.tags.setall("SYLT", [SYLT(encoding=Encoding.UTF8, lang=language, format=2, type=1, text=sylt_lyrics)])
            #print(audio.tags.get('SYLT::eng')) # Uncomment for debugging nasty SYLT syntax
            changed = True

    # USLT frame
    if not any(isinstance(frame, USLT) for frame in audio.tags.values()) or overwrite: # Embed if lyrics are not already embedded or when overwrite is True    
        if unsynced_lyrics:
            language_pattern = re.compile(r'^\[la: *(\w{2,3})\]$', re.IGNORECASE | re.MULTILINE)
            if overwrite:
                audio.tags.delall('USLT') # delete existing USLT frames to avoid duplicates
            match_lang = language_pattern.search(unsynced_lyrics)
            if match_lang:
                language = match_lang.group(1)
            else:
                language = "eng"
            uslt_frame = USLT(encoding=Encoding.UTF8, lang=language, desc='', text=unsynced_lyrics)
            audio.tags.add(uslt_frame)
            changed = True
    if changed:
        audio.save(v2_version=3) # save as id3 2.3 for compatibility
        if omitted_lines:
            results["omitted_lines"].append((mp3_file, omitted_lines))
        results["saved"].append(mp3_file)
    else:
        results["skipped"].append(mp3_file)

def embed_lyrics(file_path, lrc_path=None, txt_path=None, standardize=False, overwrite=False, results=None):
    lyrics = read_lyrics(lrc_path) if lrc_path else None
    unsynced_lyrics = read_lyrics(txt_path) if txt_path else None
    
    if file_path.lower().endswith('.flac'):
        embed_lyrics_flac(file_path, lyrics, unsynced_lyrics, standardize, overwrite, results)
    elif file_path.lower().endswith('.mp3'):
        embed_lyrics_mp3(file_path, lyrics, unsynced_lyrics, overwrite, results)
    else:
        raise ValueError("Unsupported file format. Only FLAC and MP3 are supported in import mode.")

def import_lyrics(match_categories, delete_files=False, standardize=False, progress=False, overwrite=False):
    lrc_dict = match_categories.get("lrc", {})  # Dictionary holding lrc paths categorized by extension
    txt_dict = match_categories.get("txt", {})  # Dictionary holding txt paths categorized by extension

    all_extensions = set(lrc_dict.keys()).union(set(txt_dict.keys()))  # Get all unique extensions

    files_to_delete = []  # List to store files that need to be deleted
    combined_results = {"saved": [], "skipped": [], "deleted": [], "failed": [], "omitted_lines": []}

    for ext in all_extensions:
        if ext in {"mp3", "flac"}:
            results = {"saved":[], "skipped": [], "failed": [], "omitted_lines": []}
            lrc_paths = set(lrc_dict.get(ext, []))  # Get LRC file paths for this extension
            txt_paths = set(txt_dict.get(ext, []))  # Get TXT file paths for this extension

            with tqdm(total=len(lrc_paths | txt_paths), desc=f"embedding {ext}", unit=" files", disable=not progress, ncols=100) as pbar:
                for path in lrc_paths | txt_paths:
                    base_path = os.path.splitext(path)[0]
                    lrc_path = base_path + '.lrc' if path in lrc_paths else None
                    txt_path = base_path + '.txt' if path in txt_paths else None

                    try:
                        embed_lyrics(path, lrc_path=lrc_path, txt_path=txt_path, standardize=standardize, overwrite=overwrite, results=results)

                        # Add files to delete list if delete_files is True
                        if delete_files:
                            if lrc_path:
                                files_to_delete.append(lrc_path)
                            if txt_path:
                                files_to_delete.append(txt_path)

                    except Exception as e:
                        results["failed"].append({"path": path, "error": str(e)})

                    pbar.set_postfix({"saved": len(results["saved"]), "skipped": len(results["skipped"]), "failed": len(results["failed"])})
                    pbar.update(1)

                combined_results["saved"].extend(results["saved"])
                combined_results["skipped"].extend(results["skipped"])
                combined_results["failed"].extend(results["failed"])
                combined_results["omitted_lines"].extend(results["omitted_lines"])

    # Delete files after processing all music files
    if delete_files:
        for file_path in set(files_to_delete):
            try: 
                os.remove(file_path)
                combined_results["deleted"].append(file_path)
            except:
                print(f"Failed to delete {file_path}.")

    return combined_results  # Return final results

def write_import_log(results, separate_logs, log_path):
    if not os.access(log_path, os.W_OK | os.X_OK):
        print("Cannot write log file(s) to current directory. Ensure that you have write permission. Skipping log creation.")
        return
    categories = results.keys()
    if not separate_logs:
        with open(os.path.join(log_path, f"lyrict_import_results.log"), "w", encoding="utf8") as log:
            for category in categories:
                if len(results[category]) > 0:
                    log.write(f"{category} files:\n")
                    for result_path in results[category]:
                        if isinstance(result_path, tuple):
                            log.write(result_path[0]+"\n")
                            for line in result_path[1]:
                                log.write(f"\t{line}\n")
                        elif isinstance(result_path, dict):
                            log.write(f"path: {result_path["path"]} error: {result_path["error"]}")
                        else:
                            log.write(result_path+"\n")
                    log.write("\n")
    else:
        for category in categories:
            if len(results[category]) > 0:
                with open(os.path.join(log_path, f"lyrict_import_{category}.log"), "w", encoding="utf8") as log:
                    for result_path in results[category]:
                        log.write(f"{result_path}\n")

#################################### EXPORT MUTAGEN ########################################
# Find all music files specified in -e, --extensions, default FLAC, MP3
def find_music_files(directory, extensions, single_folder, progress):
    exts = tuple(["." + extension for extension in extensions])
    music_files = []

    if not single_folder:
        with tqdm(desc="searching music", unit=" files", disable=not progress, ncols=100) as pbar:
            songs = 0
            for root, dirs, files in os.walk(directory):
                for file in files:
                    pbar.update(1)
                    if file.endswith(exts):
                        music_files.append(os.path.join(os.path.abspath(root), file))
                        songs += 1
                        pbar.set_postfix({"songs": songs})
    else:
        with tqdm(desc="searching", unit=" files", disable=not progress, ncols=100) as pbar:
            songs = 0
            for file in os.listdir(directory):
                pbar.update(1)
                if file.endswith(exts):
                    music_files.append(os.path.join(os.path.abspath(directory), file))
                    songs += 1
                    pbar.set_postfix({"songs": songs})

    if len(music_files) > 0:
        return music_files
    else:
        print("No music files found. Closing in 5 seconds.")
        sleep(5)
        sys.exit()

# Extract lyrics from MP3 and FLAC files
def extract_lyrics(music_files, progress, standardize):
    all_lyrics = {"synced": [], "unsynced": []}
    with tqdm(total=len(music_files), desc="extracting lyrics", unit=" lyrics", disable=not progress, ncols=100) as pbar:
        synced_count = 0
        unsynced_count = 0
        for file_path in music_files:
            if file_path.lower().endswith(".mp3"):
                synced, unsynced = process_mp3(file_path=file_path, all_lyrics=all_lyrics, standardize=standardize)
            elif file_path.lower().endswith(".flac"):
                synced, unsynced = process_flac(file_path=file_path, all_lyrics=all_lyrics, standardize=standardize)
            else:
                continue
            
            if synced:
                synced_count += 1
            if unsynced:
                unsynced_count += 1
            
            pbar.set_postfix({"synced": synced_count, "unsynced": unsynced_count})
            pbar.update(1)
    return all_lyrics

# Function to extract and format SYLT to LRC style
def extract_sylt_to_lrc(sylt_frame):
    lrc_lines = []
    for text, timestamp in sylt_frame.text:
        # Convert milliseconds to timedelta
        duration = timedelta(milliseconds=timestamp)
        
        # Directly extract hours, minutes, seconds, and milliseconds
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        seconds = duration.seconds % 60
        milliseconds = duration.microseconds // 1000  # Convert microseconds directly to milliseconds

        # Format the output as [hh:mm:ss.xxx] or [mm:ss.xxx]
        if hours > 0:
            timestamp_formatted = f'[{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}]'
        else:
            timestamp_formatted = f'[{minutes:02}:{seconds:02}.{milliseconds:03}]'
        lrc_line = f"{timestamp_formatted}{text}" # change "{lrc_timestamp}{text}" to "{lrc_timestamp} {text}" if you want "[00:00.000] text"
        lrc_lines.append(lrc_line)
    lrc_content = "\n".join(lrc_lines)
    return lrc_content

def process_mp3(file_path, all_lyrics, standardize):
    audio = MP3(file_path, ID3=ID3)
    synced = False
    unsynced = False

    for tag in audio.tags.values():
        if isinstance(tag, SYLT):
            # Extract language and description
            lang = tag.lang
            desc = tag.desc
            
            # Extract lyrics content in LRC format
            lrc_content = extract_sylt_to_lrc(tag)
            
            # Append tuple with file_path, LRC content, language, and description
            all_lyrics["synced"].append((file_path, lrc_content, lang, desc))
            synced = True

        elif isinstance(tag, USLT):
            # Extract language for unsynced lyrics
            lang = tag.lang
            desc = None
            
            # Append tuple with file_path, lyrics, and language
            all_lyrics["unsynced"].append((file_path, tag.text, lang, desc))
            unsynced = True

        elif isinstance(tag, TXXX) and tag.desc == "LYRICS":
            lyrics = tag.text[0]
            if standardize:
                lyrics = standardize_timestamps(lyrics, standardize)
            
            # For TXXX, there's no language field, so we append None for language
            all_lyrics["synced"].append((file_path, lyrics, None, None))
            synced = True

    return synced, unsynced

# Extract lyrics from FLAC files
def process_flac(file_path, all_lyrics, standardize):
    audio = FLAC(file_path)
    synced = False
    unsynced = False
    if "LYRICS" in audio:
        lyrics = audio["LYRICS"][0]
        if standardize:
            lyrics = standardize_timestamps(lyrics, standardize)
        all_lyrics["synced"].append((file_path, lyrics, None, None))
        synced = True
    if "UNSYNCEDLYRICS" in audio:
        all_lyrics["unsynced"].append((file_path, audio["UNSYNCEDLYRICS"][0], None, None))
        unsynced = True
    return synced, unsynced

# standardize timestamps, output formats hh:mm:ss.xxx, hh:mm:ss, mm:ss.xxx, mm:ss
def standardize_timestamps(lyrics, standardize):
    def fix_timestamp(match):
        # Split the timestamp into components
        units_split = re.match(split_timestamp_pattern, match.group(1))
        
        hours = int(units_split.group(1)) if units_split.group(1) else 0
        minutes = int(units_split.group(2))
        seconds = int(units_split.group(3))
        milliseconds = int(units_split.group(4).ljust(3, '0')) if units_split.group(4) else None
        raw_ms = units_split.group(4)

        # Use timedelta to handle atypical timestamps
        total_time = timedelta(hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds or 0)
        
        # Directly extract hours, minutes, seconds, and milliseconds
        hours = total_time.seconds // 3600
        minutes = (total_time.seconds % 3600) // 60
        seconds = total_time.seconds % 60
        milliseconds = total_time.microseconds // 1000  # Convert microseconds directly to milliseconds

        if standardize == 'keep':
            # Format the timestamp accordingly
            if hours:
                formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    if re.match(two_digit_pattern, raw_ms):
                        formatted_time += f".{raw_ms.ljust(2, '0')[:2]}"
                    elif re.match(three_digit_pattern, raw_ms):
                        formatted_time += f".{milliseconds:03}"
            else:
                formatted_time = f"{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    if re.match(two_digit_pattern, raw_ms):
                        formatted_time += f".{raw_ms.ljust(2, '0')[:2]}"
                    elif re.match(three_digit_pattern, raw_ms):
                        formatted_time += f".{milliseconds:03}"
        elif standardize == 'force.xx':
            # Format the timestamp accordingly
            if hours:
                formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    formatted_time += f".{raw_ms.ljust(2, '0')[:2]}"
                else:
                    formatted_time += ".00"
            else:
                formatted_time = f"{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    formatted_time += f".{raw_ms.ljust(2, '0')[:2]}"
                else:
                    formatted_time += ".00"
        elif standardize == 'force.xxx':
            # Format the timestamp accordingly
            if hours:
                formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    formatted_time += f".{milliseconds:03}"
                else:
                    formatted_time += ".000"
            else:
                formatted_time = f"{int(minutes):02}:{int(seconds):02}"
                if raw_ms:  # If milliseconds were present in original format
                    formatted_time += f".{milliseconds:03}"
                else:
                    formatted_time += ".000"
        return formatted_time

    # Regular expressions for matching timestamps
    timestamp_pattern = re.compile(r"(?<=[\[<])((?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?)(?=[\]>])", re.MULTILINE)
    split_timestamp_pattern = re.compile(r"(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?")
    two_digit_pattern = re.compile(r'^\d{2}$')
    three_digit_pattern = re.compile(r'^\d{3}$')

    # Replace timestamps and remove space after each timestamp in one go
    lyrics = re.sub(timestamp_pattern, fix_timestamp, lyrics)
    lyrics = re.sub(r"(\d{2}\]) +", r"\1", lyrics)

    # Reduce multiple empty lines to a single empty line
    lyrics = re.sub(r'\n{2,}', '\n\n', lyrics)

    return lyrics

# Export embedded lyrics to .lrc and .txt files
def write_lyric_files(all_lyrics, export_results, overwrite, progress, write_success):
    for lyrics_type, lyrics in all_lyrics.items():
        extension = "lrc" if lyrics_type == "synced" else "txt"
        with tqdm(total = len(lyrics), desc=f"saving {extension}", unit=f" {extension} files", disable=not progress, ncols=100) as pbar:
            language_pattern = re.compile(r'^\[la: *(\w{2,3})\]$', re.IGNORECASE | re.MULTILINE)
            saved = 0
            skipped = 0
            failed = 0
            for filename, lyrics, lang, desc in lyrics:
                pbar.update(1)
                basename = os.path.splitext(filename)[0]
                lyrics_filename = f"{basename}.{extension}"
                # Update existing language in the text if one was in the tag
                if extension == ".lrc" and lang:
                    if re.search(language_pattern, lyrics):
                        lyrics = re.sub(language_pattern, f"[la:{lang}]", lyrics)
                    else:
                        lyrics = f"[la:{lang}]\n" + lyrics
                lyrics = '\n'.join(line.strip() for line in lyrics.split('\r\n'))
                if not os.path.exists(lyrics_filename) or overwrite:
                    try:
                        with open(lyrics_filename, 'w', encoding="utf-8") as f:
                            f.write(lyrics)
                        write_success["saved"].append((filename, extension))
                        saved += 1
                        pbar.set_postfix({"saved": saved, "skipped": skipped})
                    except PermissionError:
                        write_success["failed"].append((filename, extension))
                        failed += 1
                        print(f"Failed to write {lyrics_filename} due to missing write permissions.")
                else:
                    write_success["skipped"].append((filename, extension))
                    skipped += 1
                    pbar.set_postfix({"saved": saved, "skipped": skipped})
        export_results[f"{extension}_saved"] += saved
        export_results[f"{extension}_failed"] += failed
        export_results[f"{extension}_skipped"] += skipped

# Remove embedded lyrics tags from files
def purge_tags(write_success, export_results, progress):
    saved_list = [filepath for filepath, _ in write_success["saved"]]
    skipped_list = [filepath for filepath, _ in write_success["skipped"]]
    failed_list = [filepath for filepath, _ in write_success["failed"]]
    combined_list = saved_list + skipped_list
    seen = set()
    # Filter out "failed" file paths and remove duplicates
    delete_me = [filepath for filepath in combined_list if filepath not in failed_list and (filepath not in seen and seen.add(filepath) is None)]
    if len(delete_me) > 0:
        with tqdm(total=len(delete_me), desc="purging embedded lyrics", unit=" files", disable=not progress, ncols=100) as pbar:
            purged = 0
            failed = 0
            for file_path in delete_me:
                try:
                    if file_path.lower().endswith(".mp3"):
                        audio = MP3(file_path, ID3=ID3)
                        # Remove TXXX:LYRICS, SYLT, and USLT tags
                        tags_to_remove = []
                        for tag in audio.tags.values():
                            if isinstance(tag, TXXX) and tag.desc == "LYRICS":
                                tags_to_remove.append(tag)
                            elif isinstance(tag, (SYLT, USLT)):
                                tags_to_remove.append(tag)
                        for tag in tags_to_remove:
                            audio.tags.delall(tag.HashKey)
                        # Save with ID3v2.3
                        audio.save(v2_version=3)
                        
                    elif file_path.lower().endswith(".flac"):
                        audio = FLAC(file_path)
                        # Remove TXXX:LYRICS and TXXX:UNSYNCEDLYRICS tags
                        tags_to_remove = ["LYRICS", "UNSYNCEDLYRICS"]
                        for tag in tags_to_remove:
                            if tag in audio:
                                del audio[tag]
                        # Save the file
                        audio.save()
                    purged += 1
                    pbar.set_postfix({"purged": purged, "failed": failed})
                    pbar.update(1)                    
                    
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    failed += 1
                    pbar.set_postfix({"purged": purged, "failed": failed})
                    pbar.update(1)                         
                    continue
        export_results["purged"] += purged
        export_results["failed"] += failed

# Log the results of the export to disk
def export_log(write_success, separate_logs, log_path):
    if not os.access(log_path, os.W_OK | os.X_OK):
        print("Cannot write log file(s) to current directory. Ensure that you have write permission. Skipping log creation.")
        return
    categories = write_success.keys()
    if not separate_logs:
        with open(os.path.join(log_path, f"lyrict_export_results.log"), "w", encoding="utf8") as log:
            for category in categories:
                if len(write_success[category]) > 0:
                    log.write(f"{category} lyrics:\n")
                    for result_path, extension in write_success[category]:
                        log.write(f"{result_path} to {extension}\n")
                    log.write("\n")
    else:
        for category in categories:
            if len(write_success[category]) > 0:
                with open(os.path.join(log_path, f"lyrict_export_{category}.log"), "w", encoding="utf8") as log:
                    for result_path, extension in write_success[category]:
                        log.write(f"{result_path} to {extension}\n")

#################################### TAG EXTERNAL ########################################
def get_tags(file_path, extension):
    def format_time(time_in_seconds):
        duration = timedelta(seconds=time_in_seconds)

        # Extract hours, minutes and seconds
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        seconds = duration.seconds % 60

        # Format the output as hh:mm:ss or mm:ss
        if hours > 0:
            timestamp_formatted = f'{hours:02}:{minutes:02}:{seconds:02}'
        else:
            timestamp_formatted = f'{minutes:02}:{seconds:02}'
        return timestamp_formatted

    tags = {
        "artist": None,
        "album": None,
        "title": None,
        "composer": None,
        "lyricist": None,
        "length": None
    }
    
    if extension == "flac":
        # Load FLAC file and read tags
        audio = FLAC(file_path)
        tags["artist"] = audio.get("artist", [None])[0]
        tags["album"] = audio.get("album", [None])[0]
        tags["title"] = audio.get("title", [None])[0]
        tags["composer"] = audio.get("composer", [None])[0]
        tags["lyricist"] = audio.get("lyricist", [None])[0] or audio.get("writer", [None])[0]
        tags["length"] = format_time(audio.info.length)

    elif extension == "mp3":
        # Load MP3 file and read ID3 tags
        audio = MP3(file_path, ID3=ID3)
        tags["title"] = audio.get("TIT2", TIT2()).text[0] if audio.get("TIT2") else None
        tags["artist"] = audio.get("TPE1", TPE1()).text[0] if audio.get("TPE1") else None
        tags["album"] = audio.get("TALB", TALB()).text[0] if audio.get("TALB") else None
        tags["composer"] = audio.get("TCOM", TCOM()).text[0] if audio.get("TCOM") else None
        tags["lyricist"] = audio.get("TEXT", TEXT()).text[0] if audio.get("TEXT") else None
        tags["length"] = format_time(audio.info.length)

    return tags

def rewrite_external_lyrics(lyrics_path, lyrics, tags, results, standardize):
    original_lyrics = lyrics
    if standardize and os.path.splitext(lyrics_path)[1] == ".lrc":
        lyrics = standardize_timestamps(lyrics, standardize)
    # Regular expression patterns to match all tag types
    patterns = {
        "artist": re.compile(r'^\[ar: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "album": re.compile(r'^\[al: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "title": re.compile(r'^\[ti: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "author": re.compile(r'^\[au: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "length": re.compile(r'^\[length: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "language": re.compile(r'^\[la: *(\w{2,3})\]$', re.IGNORECASE | re.MULTILINE),
        "offset": re.compile(r'^\[offset: *([+-]?\d+)\]$', re.IGNORECASE | re.MULTILINE),
        "lrc_author": re.compile(r'^\[by: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "creation_software": re.compile(r'^\[(?:re|tool): *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
        "software_version": re.compile(r'^\[ve: *(.*) *\]$', re.IGNORECASE | re.MULTILINE),
    }
    
    # Extracted data will initially be set to None
    extracted = {key: None for key in patterns}

    # Search and extract values for each tag using the patterns
    for key, pattern in patterns.items():
        match = pattern.search(lyrics)
        if match:
            extracted[key] = match.group(1)  # Capture the first group, which is the tag value
            lyrics = pattern.sub('', lyrics)  # Remove matched tag line from lyrics

    # Decide on "author" field with preference for lyricist if present
    final_tags = {key: tags.get(key) or extracted[key] for key in extracted}
    final_tags["author"] = tags.get("lyricist") or extracted["author"] or tags.get("composer")

    # Create new header lines with non-None final tags
    header_lines = []
    if final_tags["artist"]:
        header_lines.append(f"[ar:{final_tags['artist']}]")
    if final_tags["album"]:
        header_lines.append(f"[al:{final_tags['album']}]")
    if final_tags["title"]:
        header_lines.append(f"[ti:{final_tags['title']}]")
    if final_tags["author"]:
        header_lines.append(f"[au:{final_tags['author']}]")
    if final_tags["length"]:
        header_lines.append(f"[length:{final_tags['length']}]")
    if final_tags["language"]:
        header_lines.append(f"[la:{final_tags['language']}]")
    if final_tags["offset"]:
        header_lines.append(f"[offset:{final_tags['offset']}]")
    if final_tags["lrc_author"]:
        header_lines.append(f"[by:{final_tags['lrc_author']}]")
    if final_tags["creation_software"]:
        header_lines.append(f"[re:{final_tags['creation_software']}]")
    if final_tags["software_version"]:
        header_lines.append(f"[ve:{final_tags['software_version']}]")

    # Combine header and cleaned lyrics
    updated_lyrics = "\n".join(header_lines + [lyrics.strip()])

    # If nothing changed, don't rewrite the lyrics
    if original_lyrics == updated_lyrics:
        results["skipped"].append(lyrics_path)
        return

    # Write updated lyrics back to the file
    try:
        with open(lyrics_path, 'w', encoding='utf-8') as file:
            file.write(updated_lyrics)
        results["fixed"].append(lyrics_path)
    except PermissionError:
        results["failed"].append(lyrics_path)
        print(f"Could not open {lyrics_path} for writing.")

def write_tag_external_log(results, separate_logs, log_path):
    if not os.access(log_path, os.W_OK | os.X_OK):
        print("Cannot write log file(s) to current directory. Ensure that you have write permission. Skipping log creation.")
        return
    categories = results.keys()
    if not separate_logs:
        with open(os.path.join(log_path, f"lyrict_tag_external_results.log"), "w", encoding="utf8") as log:
            for category in categories:
                if len(results[category]) > 0:
                    log.write(f"{category} files:\n")
                    for result_path in sorted(set(results[category])):
                            log.write(result_path+"\n")
                    log.write("\n")
    else:
        for category in categories:
            if len(results[category]) > 0:
                with open(os.path.join(log_path, f"lyrict_tag_external_{category}.log"), "w", encoding="utf8") as log:
                    for result_path in sorted(set(results[category])):
                        log.write(f"{result_path}\n")
        
def main(args):
    directory = args.directory
    delete = args.delete
    extensions = args.extensions
    log_to_disk = args.log_to_disk
    separate_logs = args.separate_logs
    log_path = args.log_path
    overwrite = args.overwrite
    progress = args.progress
    single_folder = args.single_folder
    import_mode = args.import_mode
    export_mode = args.export_mode
    test_run = args.test_mode
    tag_external_mode = args.tag_external_mode
    mp3tag = args.mp3tag_mode
    standardize = args.standardize

    # Find lyrics files for modes that require them
    if test_run or mp3tag or import_mode or tag_external_mode:
        lyrics_files = find_lyrics_files(directory=directory, single_folder=single_folder, progress=progress)

    if test_run:
        match_categories = find_matches(lyrics_files=lyrics_files, extensions=extensions, progress=progress)
        if log_to_disk:
            write_log(match_categories=match_categories, separate_logs=separate_logs, log_path=log_path)
        errors = False
        for lyrics_type, audio_types in match_categories.items():
            if "unlinked" in audio_types:
                print(f"{lyrics_type.upper()} files without linked songs found:")
                for path in match_categories[lyrics_type]["unlinked"]:
                    print(path)
                errors = True
        if errors:
            print("Unlinked lyrics found. Closing in 5 seconds.")
            sleep(5)
            sys.exit()
        else:
            print(f"No unlinked lyrics files found, closing in 5 seconds.")
            sleep(5)
            sys.exit()

    if mp3tag:
        action_folder = os.path.join(os.getenv('APPDATA')+"\\Mp3tag\\data\\actions\\")
        match_categories = find_matches(lyrics_files=lyrics_files, extensions=extensions, progress=progress)
        if log_to_disk:
            write_log(match_categories=match_categories, separate_logs=separate_logs, log_path=log_path)
        mp3tag_open_songs(match_categories=match_categories, action_folder=action_folder, overwrite=overwrite)

    if import_mode:
        match_categories = find_matches(lyrics_files=lyrics_files, extensions=extensions, progress=progress)
        results = import_lyrics(match_categories=match_categories, delete_files=delete, standardize=standardize, progress=progress, overwrite=overwrite)
        if log_to_disk:
            write_import_log(results=results, separate_logs=separate_logs, log_path=log_path)
        # Assign the counts for the human readable output.
        saved, skipped, failed, deleted, omitted = map(len, (results["saved"], results["skipped"], results["failed"], results["deleted"], results["omitted_lines"]))
        print(f"{saved} embedded, {skipped} skipped, {omitted} files with omitted lines, {failed} failed, {deleted} external lyrics deleted.")
        print("Closing in 5 seconds.")
        sleep(5)
        sys.exit()

    if export_mode:
        music_files = find_music_files(directory=directory, extensions=extensions, single_folder=single_folder, progress=progress)
        all_lyrics = extract_lyrics(music_files=music_files, progress=progress, standardize=standardize)
        write_success = {"saved":[], "skipped":[], "failed":[]}

        export_results = defaultdict(int)

        if all_lyrics["synced"] or all_lyrics["unsynced"]:
            write_lyric_files(all_lyrics=all_lyrics, export_results=export_results, overwrite=overwrite, progress=progress, write_success=write_success)
          
        if log_to_disk:
            export_log(write_success=write_success, separate_logs=separate_logs, log_path=log_path)

        if delete:
            purge_tags(write_success=write_success, export_results=export_results, progress=progress)
        
        print(f"\n{len(music_files)} music files processed, {len(all_lyrics["synced"])} synced lyrics and {len(all_lyrics["unsynced"])} unsynced lyrics found.")
        if any(export_results[key] > 0 for key in ("lrc_saved", "lrc_skipped", "lrc_failed")):
            print(f"{export_results["lrc_saved"]} synced lyrics written to disk, {export_results["lrc_skipped"]} skipped, {export_results["lrc_failed"]} errors.")
        if any(export_results[key] > 0 for key in ("txt_saved", "txt_skipped", "txt_failed")):
            print(f"{export_results["txt_saved"]} unsynced lyrics written to disk, {export_results["txt_skipped"]} skipped, {export_results["txt_failed"]} errors.")
        if export_results["purged"] > 0 or export_results["failed"] > 0:
            print(f"Deleted embedded lyrics of {export_results["purged"]} files, encountered {export_results["failed"]} errors.")
        print("Closing in 5 seconds.")
        sleep(5)
        sys.exit()

    if tag_external_mode:
        supported_extensions = ["mp3", "flac"]
        match_categories = find_matches(lyrics_files=lyrics_files, extensions=supported_extensions, progress=progress)
        results = {"fixed":[], "skipped":[], "failed":[]}

        for lyrics_type, audio_types in match_categories.items():
            for ext in supported_extensions:
                if ext in audio_types:
                    with tqdm(total = len(audio_types[ext]), desc= f"fixing {ext} {lyrics_type}s", unit=f" {lyrics_type} files", disable=not progress, ncols=100) as pbar:
                        for song_path in audio_types[ext]:
                            lyrics_path = os.path.splitext(song_path)[0] + f".{lyrics_type}"
                            lyrics = read_lyrics(lyrics_path)
                            tags = get_tags(file_path=song_path, extension=ext)
                            rewrite_external_lyrics(lyrics_path=lyrics_path, lyrics=lyrics, tags=tags, results=results, standardize=standardize)
                            pbar.update(1)

        fixed = len(set(results["fixed"]))
        skipped = len(set(results["skipped"]))
        failed = len(set(results["failed"]))
        if log_to_disk:
            write_tag_external_log(results, separate_logs, log_path)
        print(f"{fixed} fixed, {skipped} skipped, {failed} failed.")
        print("Closing in 5 seconds.")
        sleep(5)
        sys.exit()

if __name__ == "__main__":
    args = parse_arguments()
    try:
        main(args)
    except KeyboardInterrupt:
        print("Interrupted, exiting.")
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)