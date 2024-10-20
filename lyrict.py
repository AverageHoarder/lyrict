import os
import sys
import re
import subprocess
import shutil
import getpass
import argparse
import itertools
from time import sleep
from tqdm import tqdm
from datetime import timedelta
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT, Encoding
from mutagen.id3._frames import TXXX
from mutagen.id3._util import ID3NoHeaderError

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
        
    parser = argparse.ArgumentParser(description='Test .lrc and .txt lyrics for broken links, embed synced and unsynced lyrics into tags or extract them from tags to files.')
    parser.add_argument('-d', '--directory',
                        help='Test, Import, mp3tag: The directory to scan for .lrc and .txt files. Export: Directory to scan for music files.',
                        type=dir_path, default=".", const=".", nargs="?")
    parser.add_argument('--delete', action='store_true',
                        help=f'''Import: After successful import, deletes external .lrc and .txt files from disk.
Export: After successful export, deletes LYRICS, SYLT and USLT tags from mp3 files and LYRICS and UNSYNCEDLYRICS tags from flac files.''')     
    parser.add_argument('-e', '--extensions',
                        help='''Test, Import, mp3tag: List of song extensions the script will look for, default: flac and mp3. 
Export: Song extensions that will be scanned for embedded lyrics, default flac and mp3''',
                        nargs='+', default=["flac", "mp3"])
    parser.add_argument('--export', action='store_true',
                        help=f'''Export embedded lyrics of flac and mp3 files. Synced lyrics (LYRICS, SYLT) to .lrc and unsynced lyrics (UNSYNCEDLYRICS/USLT) to .txt files. 
Requires mutagen, use "pip3 install mutagen" to install it''')
    parser.add_argument('-l', '--log', action='count',
                        help='''Test, mp3tag: Log filepaths (lyric and music extension) to "lyrict_results.log". 
"-ll" logs each filetype separately (lrc_flac.log, txt_mp3.log...) instead.
Import, Export: log embedding/exporting results to "lyrict_import_results"/"lyrict_export_results"''')
    parser.add_argument('--log_path',
                        help='The directory to save logs to when used with -l or -ll, defaults to "."',
                        type=dir_path, default=".", const=".", nargs="?")
    parser.add_argument('-m', choices=['export', 'import', 'mp3tag', 'test'], required=True,
                        help="""Mode, use 'test' to only log linked/unlinked songs to console or to file(s) when used with -l or -ll.
Use 'mp3tag' to embed external lyrics (.txt/.lrc) in audio tags via mp3tag.
Use 'import' to embed external lyrics (.txt/.lrc) in audio tags via mutagen.
Use 'export' to export embedded tags to external files (.lrc/.txt) via mutagen.
""")
    parser.add_argument('-o', '--overwrite', action='store_true',
                        help='''mp3tag: Overwrite/recreate the mp3tag actions to reflect changes made in the config section.
Import: Purge and overwrite existing embedded lyrics tags (LYRICS/UNSYNCEDLYRICS/SYLT/USLT)
Export: Overwrite the content of existing .lrc/.txt files.''')
    parser.add_argument('-p', '--progress', action='store_true',
                        help='Show progress bars. Useful for huge directories. Requires tqdm, use "pip3 install tqdm" to install it.')       
    parser.add_argument('-s', '--single_folder', action='store_true',
                        help='Test, Import, mp3tag: Only scans a single folder for .lrc and .txt files, no subdirectories. Export: Only scans a single folder for music files.')
    parser.add_argument('--standardize', action='store_true',
                        help=f'Import/Export: standardize and fix timestamps of synced lyrics to `[mm:ss.xxx]text`, `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` formats (depending on their source format)')

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
    if args.m == 'export':
        setattr(args, "export_mode", True)
    elif args.m == 'import':
        setattr(args, "import_mode", True)
    elif args.m == 'test':
        setattr(args, "test_mode", True)
    elif args.m == 'mp3tag':
        setattr(args, "mp3tag_mode", True)

    return args

########################################## SHARED ############################################
# Find all .lrc and .txt files in the directory specified with -d, recursively if not called with -s, --single
def find_lrc_files(directory, single_folder, progress):
    lrc_files = []
    txt_files = []
    pattern = r'^\d{2,3}\s' # Pattern to filter .txt files, default filters for names starting with 2 or 3 digits and a space, like "01 Hello.flac"

    if not single_folder:
        with tqdm(desc="searching", unit=" files", disable=not progress) as pbar:
            lrc_count = 0
            txt_count = 0
            for root, dirs, files in os.walk(directory):
                for file in files:
                    pbar.update(1)
                    if file.endswith(".lrc"):
                        lrc_files.append(os.path.join(os.path.abspath(root), file))
                        lrc_count += 1
                        pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})
                    elif file.endswith(".txt") and re.match(pattern, file):
                        txt_files.append(os.path.join(os.path.abspath(root), file))
                        txt_count += 1
                        pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})
    else:
        with tqdm(desc="searching", unit=" files", disable=not progress) as pbar:
            lrc_count = 0
            txt_count = 0
            for file in os.listdir(directory):
                if file.endswith(".lrc"):
                    lrc_files.append(os.path.join(os.path.abspath(directory), file))
                    lrc_count += 1
                    pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})              
                elif file.endswith(".txt")and re.match(pattern, file):
                    txt_files.append(os.path.join(os.path.abspath(directory), file))
                    txt_count += 1
                    pbar.set_postfix({"lrc": lrc_count, "txt": txt_count})

    if len(lrc_files) == 0:
        lrc_files = None
    if len(txt_files) == 0:
        txt_files = None
    if not lrc_files and not txt_files:
        print("No external lyrics (.lrc/.txt) found, closing in 5 seconds.")
        sleep(5)
        sys.exit()
    else:
        return lrc_files, txt_files

# Find matching songs from -e, --extensions list for .lrc and .txt files
def find_matches(lyric_paths, file_ext, extensions, progress):
    match_categories = dict.fromkeys(extensions)
    for ext in extensions:
        match_categories[ext] = []
    match_categories["unlinked"] = []
    with tqdm(total = len(lyric_paths), desc= f"finding {file_ext} matches", unit=f" {file_ext} files", disable=not progress) as pbar:
        for song in lyric_paths:
            hits = False
            for ext in extensions:
                song_path = os.path.splitext(song)[0] + f'.{ext}'
                if os.path.isfile(song_path):
                    match_categories[ext].append(song_path)
                    hits = True
                    pbar.update(1)
            if not hits:
                match_categories["unlinked"].append(song)
    match_categories = {key: value for key, value in match_categories.items() if value != []}
    return match_categories

##################################### IMPORT MP3TAG #############################################
# Open only songs with matching lyrics in mp3tag via CLI
def add_to_mp3tag(match_categories, first_track=True):
    for ext in match_categories.keys():
        for track in match_categories[ext]:
            if first_track:
                try:
                    subprocess.Popen(["mp3tag", "/fn:" + track])
                except subprocess.CalledProcessError:
                    print(f"Error while opening {track} in mp3tag.")
                first_track = False
                sleep(1)
            else:
                try:
                    subprocess.run(["mp3tag", "/add", "/fn:" + track])
                except subprocess.CalledProcessError:
                    print(f"Error while adding {track} to mp3tag.")
    return

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
def mp3tag_create_actions(action_folder, overwrite_actions, extensions):
    class Mp3tagAction:
        action_list = []
        def __init__(self, name, content):
            self.name = name
            self.path = os.path.join(action_folder + name + ".mta")
            self.content = content
            Mp3tagAction.action_list.append(self)
        def create(self):
            choice = ""
            if os.path.isfile(self.path) and not overwrite_actions:
                return
            if not overwrite_actions:
                choice = input(f"Create a mp3tag action called '{self.name}' in:\n{action_folder}? (y/n): ")
            if choice == "y" or overwrite_actions:
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
def mp3tag_flow_both(match_categories_lrc, match_categories_txt, action_folder, overwrite_actions, extensions):
    errors = False
    if "unlinked" in match_categories_lrc.keys():
        print(f"LRC files without linked songs found:")
        for file_path in match_categories_lrc["unlinked"]:
            print(file_path)
        del match_categories_lrc["unlinked"]
        errors = True
    if "unlinked" in match_categories_txt.keys():
        print(f"TXT files without linked songs found:")
        for file_path in match_categories_txt["unlinked"]:
            print(file_path)
        del match_categories_txt["unlinked"]
        errors = True
    
    if errors and len(match_categories_lrc) > 0 or errors and len(match_categories_txt) > 0:
        choice = input(f"Open songs with external lyrics in mp3tag anyhow? (y/n): ")
        if choice == "y":
            mp3tag_on_path()
            if not os.path.isdir(action_folder):
                print(f"{action_folder} not found, skipping action creation.")
            else:
                mp3tag_create_actions(action_folder, overwrite_actions, extensions)
            first_execution = True
            if len(match_categories_lrc) > 0:
                add_to_mp3tag(match_categories_lrc, first_execution)
                first_execution = False
            if len(match_categories_txt) > 0:
                add_to_mp3tag(match_categories_txt, first_execution)
        else:
            print("Exiting.")
            sys.exit()
    else:
        if len(match_categories_lrc) > 0 or len(match_categories_txt) > 0:
            choice = input(f"Open songs with external lyrics in mp3tag? (y/n): ")
            if choice == "y":
                mp3tag_on_path()
                if not os.path.isdir(action_folder):
                    print(f"{action_folder} not found, skipping action creation.")
                else:
                    mp3tag_create_actions(action_folder, overwrite_actions, extensions)
                first_execution = True
                if len(match_categories_lrc) > 0:
                    add_to_mp3tag(match_categories_lrc, first_execution)
                    first_execution = False
                if len(match_categories_txt) > 0:
                    add_to_mp3tag(match_categories_txt, first_execution)
            else:
                print("Exiting.")
                sys.exit()

# Open songs with only one type of matching lyrics (synced/unsynced) in mp3tag
def mp3tag_flow_single(match_categories, action_folder, overwrite_actions, extensions, file_ext):
    if "unlinked" in match_categories.keys():
        print(f"{file_ext.upper()} files without linked songs found:")
        for file_path in match_categories["unlinked"]:
            print(file_path)
        del match_categories["unlinked"]
        if len(match_categories) > 0:
            choice = input(f"Open songs with external {file_ext} lyrics in mp3tag anyhow? (y/n): ")
            if choice == "y":
                mp3tag_on_path()
                if not os.path.isdir(action_folder):
                    print(f"{action_folder} not found, skipping action creation.")
                else:
                    mp3tag_create_actions(action_folder, overwrite_actions, extensions)
                add_to_mp3tag(match_categories)
            else:
                print("Exiting.")
                sys.exit()
        else:
            sys.exit()
    else:
        if len(match_categories) > 0:
            choice = input(f"Open songs with external {file_ext} lyrics in mp3tag? (y/n): ")
            if choice == "y":
                mp3tag_on_path()
                if not os.path.isdir(action_folder):
                    print(f"{action_folder} not found, skipping action creation.")
                else:
                    mp3tag_create_actions(action_folder, overwrite_actions, extensions)
                add_to_mp3tag(match_categories)
            else:
                print("Exiting.")
                sys.exit()
        else:
            sys.exit()

# Log found lrc paths to disk, grouped by extension and if there is a matching song
def write_log(match_categories, lyrics_ext, separate_logs, log_path):
    if not os.access(log_path, os.W_OK | os.X_OK):
        print("Cannot write log file(s) to current directory. Ensure that you have write permission. Skipping log creation.")
        return
    categories = match_categories.keys()
    if not separate_logs:
        with open(os.path.join(log_path, f"lyrict_{lyrics_ext}_results.log"), "w", encoding="utf8") as log:
            for category in categories:
                log.write(f"{category} results:\n")
                for result_path in match_categories[category]:
                    log.write(result_path+"\n")
                log.write("\n")
    else:
        for category in categories:
            with open(os.path.join(log_path, f"{lyrics_ext}_{category}.log"), "w", encoding="utf8") as log:
                for result_path in match_categories[category]:
                    log.write(result_path+"\n")

#################################### IMPORT MUTAGEN ########################################
def read_lyrics(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def parse_lrc_to_sylt(lyrics):
    sylt_lyrics = []
    language_pattern = re.compile(r'^\[la: *(\w{2,3})\]$')
    offset_pattern = re.compile(r'^\[offset: *([+-]\d+)\]$')
    timestamp_pattern = re.compile(r'^\[(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?\] *(?!(?:.*<\d{1,3}:|\[\d{1,3}:))(.*)$')
    mutli_timestamp_check_pattern = re.compile(r'^(?:\[(?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?\]){2,}.*$')
    multi_timestamp_pattern = re.compile(r'(\[(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?\])')
    multi_text_pattern = re.compile(r'^(?:\[(?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?\])+ *(.*)$')
    lines = lyrics.split('\n')
    omitted_lines = []
    language = ""
    offset = 0
    # Determine language and offset
    for line in itertools.islice(lines, 20):
        match_lang = re.match(language_pattern, line)
        match_offset = re.match(offset_pattern, line)
        if match_lang:
            language = match_lang.group(1)
        if match_offset:
            offset = int(match_offset.group(1))
    # Default to English if no language tag was detected in the .lrc file
    if not language:
        language = "eng"

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
                lyrics = standardize_timestamps(lyrics)
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
            language_pattern = re.compile(r'^\[la: *(\w{2,3})\]$')
            if overwrite:
                audio.tags.delall('USLT') # delete existing USLT frames to avoid duplicates
            for line in unsynced_lyrics:
                if re.match(language_pattern, line):
                    language == re.match(language_pattern, line).group(1)
                else:
                    language == "eng"
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
        raise ValueError("Unsupported file format. Only FLAC and MP3 are supported.")

def import_lyrics(match_categories_lrc={}, match_categories_txt={}, delete_files=False, standardize=False, progress=False, overwrite=False):
    all_extensions = set(match_categories_lrc.keys()).union(set(match_categories_txt.keys()))
    files_to_delete = []  # List to store files that need to be deleted
    combined_results = {"saved": [], "skipped": [], "deleted": [], "failed": [], "omitted_lines": []}

    for ext in all_extensions:
        if ext == "mp3" or ext == "flac":
            results = {"saved":[], "skipped": [], "failed": [], "omitted_lines": []}
            lrc_paths = set(match_categories_lrc.get(ext, []))
            txt_paths = set(match_categories_txt.get(ext, []))
            with tqdm(total=len(lrc_paths | txt_paths), desc=f"embedding {ext}", unit=" files", disable=not progress) as pbar:
                for path in lrc_paths | txt_paths:
                    base_path = os.path.splitext(path)[0]
                    lrc_path = base_path + '.lrc'
                    txt_path = base_path + '.txt'
                    try:
                        if path in lrc_paths and path in txt_paths:
                            embed_lyrics(path, lrc_path=lrc_path, txt_path=txt_path, standardize=standardize, overwrite=overwrite, results=results)
                        elif path in lrc_paths:
                            embed_lyrics(path, lrc_path=lrc_path, standardize=standardize, overwrite=overwrite, results=results)
                        elif path in txt_paths:
                            embed_lyrics(path, txt_path=txt_path, standardize=standardize, overwrite=overwrite, results=results)
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
        else:
            continue     
    # Delete files after processing all music files
    if delete_files:
        for file_path in set(files_to_delete):
            os.remove(file_path)
            combined_results["deleted"].append(file_path)
    return combined_results

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
        with tqdm(desc="searching music", unit=" files", disable=not progress) as pbar:
            songs = 0
            for root, dirs, files in os.walk(directory):
                for file in files:
                    pbar.update(1)
                    if file.endswith(exts):
                        music_files.append(os.path.join(os.path.abspath(root), file))
                        songs += 1
                        pbar.set_postfix({"songs": songs})
    else:
        with tqdm(desc="searching", unit=" files", disable=not progress) as pbar:
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
def extract_lyrics(file_paths, progress, standardize):
    synced_lyrics = []
    unsynced_lyrics = []
    with tqdm(total=len(file_paths), desc="extracting lyrics", unit=" lyrics", disable=not progress) as pbar:
        synced_count = 0
        unsynced_count = 0
        for file_path in file_paths:
            if file_path.lower().endswith(".mp3"):
                synced, unsynced = process_mp3(file_path, synced_lyrics, unsynced_lyrics, standardize)
            elif file_path.lower().endswith(".flac"):
                synced, unsynced = process_flac(file_path, synced_lyrics, unsynced_lyrics, standardize)
            else:
                continue
            
            if synced:
                synced_count += 1
            if unsynced:
                unsynced_count += 1
            
            pbar.set_postfix({"synced": synced_count, "unsynced": unsynced_count})
            pbar.update(1)
    return synced_lyrics, unsynced_lyrics

# Function to extract and format SYLT to LRC style
def extract_sylt_to_lrc(sylt_frame):
    lrc_lines = []
    for text, timestamp in sylt_frame.text:
        # Convert milliseconds to timedelta
        duration = timedelta(milliseconds=timestamp)
        
        # Extract hours, minutes, seconds, and milliseconds
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = duration.microseconds // 1000  # Get milliseconds

        # Format the output as [hh:mm:ss.xxx] or [mm:ss.xxx]
        if hours > 0:
            timestamp_formatted = f'[{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}]'
        else:
            timestamp_formatted = f'[{minutes:02}:{seconds:02}.{milliseconds:03}]'
        lrc_line = f"{timestamp_formatted}{text}" # change "{lrc_timestamp}{text}" to "{lrc_timestamp} {text}" if you want "[00:00.00] text"
        lrc_lines.append(lrc_line)
    lrc_content = "\n".join(lrc_lines)
    return lrc_content

def process_mp3(file_path, synced_lyrics, unsynced_lyrics, standardize):
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
            synced_lyrics.append((file_path, lrc_content, lang, desc))
            synced = True

        elif isinstance(tag, USLT):
            # Extract language for unsynced lyrics
            lang = tag.lang
            desc = None
            
            # Append tuple with file_path, lyrics, and language
            unsynced_lyrics.append((file_path, tag.text, lang, desc))
            unsynced = True

        elif isinstance(tag, TXXX) and tag.desc == "LYRICS":
            lyrics = tag.text[0]
            if standardize:
                lyrics = standardize_timestamps(lyrics)
                
            # For TXXX, there's no language field, so we append None for language
            synced_lyrics.append((file_path, lyrics, None, None))
            synced = True

    return synced, unsynced

# Extract lyrics from FLAC files
def process_flac(file_path, synced_lyrics, unsynced_lyrics, standardize):
    audio = FLAC(file_path)
    synced = False
    unsynced = False
    if "LYRICS" in audio:
        lyrics = audio["LYRICS"][0]
        if standardize:
            lyrics = standardize_timestamps(lyrics)
        synced_lyrics.append((file_path, lyrics, None, None))
        synced = True
    if "UNSYNCEDLYRICS" in audio:
        unsynced_lyrics.append((file_path, audio["UNSYNCEDLYRICS"][0], None, None))
        unsynced = True
    return synced, unsynced

# standardize timestamps, output formats hh:mm:ss.xxx, hh:mm:ss, mm:ss.xxx, mm:ss
def standardize_timestamps(lyrics):
    def fix_timestamp(match):
        # Split the timestamp into components
        units_split = re.match(split_timestamp_pattern, match.group(1))
        
        hours = int(units_split.group(1)) if units_split.group(1) else 0
        minutes = int(units_split.group(2))
        seconds = int(units_split.group(3))
        milliseconds = int(units_split.group(4)) if units_split.group(4) else None

        # Use timedelta to handle atypical timestamps
        total_time = timedelta(hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds or 0)
        
        # Convert the timedelta back into hours, minutes, seconds, and milliseconds
        total_seconds = total_time.total_seconds()
        hours, remainder = divmod(total_seconds, 3600)
        minutes, remainder = divmod(remainder, 60)
        seconds = int(remainder)
        milliseconds = int((remainder - seconds) * 1000)

        # Format the timestamp accordingly
        if hours:
            formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
            if units_split.group(4) is not None:  # If milliseconds were present in original format
                formatted_time += f".{milliseconds:03}"
        else:
            formatted_time = f"{int(minutes):02}:{int(seconds):02}"
            if units_split.group(4) is not None:  # If milliseconds were present in original format
                formatted_time += f".{milliseconds:03}"
        return formatted_time

    # Regular expressions for matching timestamps
    timestamp_pattern = re.compile(r"(?<=[\[<])((?:\d{1,2}:)?\d{1,3}:\d{1,2}(?:\.\d{2,3})?)(?=[\]>])")
    split_timestamp_pattern = re.compile(r"(?:(\d{1,2}):)?(\d{1,3}):(\d{1,2})(?:\.(\d{2,3}))?")

    # Split lyrics into lines
    lines = lyrics.split('\n')
    standardized_lyrics = []

    # Process each line
    for line in lines:
        # First, replace the timestamp with standardized format
        standardized_line = re.sub(timestamp_pattern, fix_timestamp, line)
        
        # Then, remove any space immediately after the closing bracket of the timestamp
        standardized_line = re.sub(r"(\])\s+", r"\1", standardized_line)
        
        standardized_lyrics.append(standardized_line)
    
    return '\n'.join(standardized_lyrics)


# Export embedded lyrics to .lrc and .txt files
def write_lrc_files(lyrics, extension, overwrite, progress, write_success):
    with tqdm(total = len(lyrics), desc=f"saving {extension}", unit=f" {extension} files", disable=not progress) as pbar:
        saved = 0
        skipped = 0
        failed = 0
        for filename, lyrics, lang, desc in lyrics:
            pbar.update(1)
            basename = os.path.splitext(filename)[0]
            lyrics_filename = basename + extension
            language_pattern = r'\[la: *(\w{2,3})\]'
            if extension == ".lrc" and lang is not None:
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
    return saved, skipped, failed

# Remove embedded lyrics tags from files
def purge_tags(write_success, progress):
    saved_list = [filepath for filepath, _ in write_success["saved"]]
    skipped_list = [filepath for filepath, _ in write_success["skipped"]]
    failed_list = [filepath for filepath, _ in write_success["failed"]]
    combined_list = saved_list + skipped_list
    seen = set()
    # Filter out "failed" file paths and remove duplicates
    delete_me = [filepath for filepath in combined_list if filepath not in failed_list and (filepath not in seen and seen.add(filepath) is None)]
    if len(delete_me) > 0:
        with tqdm(total=len(delete_me), desc="purging embedded lyrics", unit=" files", disable=not progress) as pbar:
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
        return purged, failed

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
    mp3tag = args.mp3tag_mode
    standardize = args.standardize

    if test_run:
        lrc_paths, txt_paths = find_lrc_files(directory, single_folder, progress)
        if lrc_paths and txt_paths:
            match_categories_lrc = find_matches(lrc_paths, "lrc", extensions, progress)
            match_categories_txt = find_matches(txt_paths, "txt", extensions, progress)
            if log_to_disk:
                write_log(match_categories_lrc, "lrc", separate_logs, log_path)
                write_log(match_categories_txt, "txt", separate_logs, log_path)
            errors = False
            if "unlinked" in match_categories_lrc.keys():
                print(f"LRC files without linked songs found:")
                for file_path in match_categories_lrc["unlinked"]:
                    print(file_path)
                errors = True
            if "unlinked" in match_categories_txt.keys():
                print(f"TXT files without linked songs found:")
                for file_path in match_categories_txt["unlinked"]:
                    print(file_path)
                errors = True
            if errors:
                print("Unlinked lyrics found. Closing in 5 seconds.")
                sleep(5)
                sys.exit()
            else:
                print(f"No unlinked lyrics files found, closing in 5 seconds.")
                sleep(5)
                sys.exit()
        elif lrc_paths and not txt_paths:
            match_categories = find_matches(lrc_paths, "lrc", extensions, progress)
            if log_to_disk:
                write_log(match_categories, "lrc", separate_logs, log_path)
            if "unlinked" in match_categories.keys():
                print("LRC files without linked songs found:")
                for file_path in match_categories["unlinked"]:
                    print(file_path)
                print("Closing in 5 seconds.")
                sleep(5)
                sys.exit()
            else:
                print(f"No unlinked LRC files found, closing in 5 seconds.")
                sleep(5)
                sys.exit()
        elif not lrc_paths and txt_paths:
            match_categories = find_matches(txt_paths, "txt", extensions, progress)
            if log_to_disk:
                write_log(match_categories, "txt", separate_logs, log_path)
            if "unlinked" in match_categories.keys():
                print("TXT files without linked songs found:")
                for file_path in match_categories["unlinked"]:
                    print(file_path)
                print("Closing in 5 seconds.")
                sleep(5)
                sys.exit()
            else:
                print(f"No unlinked LRC files found, closing in 5 seconds.")
                sleep(5)
                sys.exit()

    if mp3tag:
        action_folder = os.path.join(os.getenv('APPDATA')+"\\Mp3tag\\data\\actions\\")
        lrc_paths, txt_paths = find_lrc_files(directory, single_folder, progress)
        if lrc_paths and txt_paths:
            match_categories_lrc = find_matches(lrc_paths, "lrc", extensions, progress)
            match_categories_txt = find_matches(txt_paths, "txt", extensions, progress)
            if log_to_disk:
                write_log(match_categories_lrc, "lrc", separate_logs, log_path)
                write_log(match_categories_txt, "txt", separate_logs, log_path)
            mp3tag_flow_both(match_categories_lrc, match_categories_txt, action_folder, overwrite, extensions)
        elif lrc_paths and not txt_paths:
            match_categories = find_matches(lrc_paths, "lrc", extensions, progress)
            if log_to_disk:
                write_log(match_categories, "lrc", separate_logs, log_path)
            mp3tag_flow_single(match_categories, action_folder, overwrite, extensions, "lrc")
        elif not lrc_paths and txt_paths:
            match_categories = find_matches(txt_paths, "txt", extensions, progress)
            if log_to_disk:
                write_log(match_categories, "txt", separate_logs, log_path)
            mp3tag_flow_single(match_categories, action_folder, overwrite, extensions, "txt")

    if import_mode:
        lrc_paths, txt_paths = find_lrc_files(directory, single_folder, progress)
        if lrc_paths and txt_paths:
            match_categories_lrc = find_matches(lrc_paths, "lrc", extensions, progress)
            match_categories_txt = find_matches(txt_paths, "txt", extensions, progress)
            results = import_lyrics(match_categories_lrc=match_categories_lrc,
                                    match_categories_txt=match_categories_txt,
                                    delete_files=delete,
                                    standardize=standardize,
                                    progress=progress,
                                    overwrite=overwrite)
            if log_to_disk:
                write_import_log(results, separate_logs, log_path)
            saved = len(results["saved"])
            skipped = len(results["skipped"])
            failed = len(results["failed"])
            deleted = len(results["deleted"])
            omitted = len(results["omitted_lines"])
            print(f"{saved} embedded, {skipped} skipped, {omitted} files with omitted lines, {failed} failed, {deleted} external lyrics deleted.")
        elif lrc_paths and not txt_paths:
            match_categories_lrc = find_matches(lrc_paths, "lrc", extensions, progress)
            results = import_lyrics(match_categories_lrc=match_categories_lrc,
                                    delete_files=delete,
                                    standardize=standardize,
                                    progress=progress,
                                    overwrite=overwrite)
            if log_to_disk:
                write_import_log(results, separate_logs, log_path)
            saved = len(results["saved"])
            skipped = len(results["skipped"])
            failed = len(results["failed"])
            deleted = len(results["deleted"])
            omitted = len(results["omitted_lines"])
            print(f"{saved} embedded, {skipped} skipped, {omitted} files with omitted lines, {failed} failed, {deleted} external lyrics deleted.")
        elif not lrc_paths and txt_paths:
            match_categories_txt = find_matches(lrc_paths, "txt", extensions, progress)
            results = import_lyrics(match_categories_txt=match_categories_txt,
                                    delete_files=delete,
                                    standardize=standardize,
                                    progress=progress,
                                    overwrite=overwrite)
            if log_to_disk:
                write_import_log(results, separate_logs, log_path)
            saved = len(results["saved"])
            skipped = len(results["skipped"])
            failed = len(results["failed"])
            deleted = len(results["deleted"])
            print(f"{saved} embedded, {skipped} skipped, {failed} failed, {deleted} external lyrics deleted.")

    if export_mode:
        music_files = find_music_files(directory, extensions, single_folder, progress)
        synced_lyrics, unsynced_lyrics = extract_lyrics(music_files, progress, standardize)
        write_success = {"saved":[], "skipped":[], "failed":[]}
        lrc_saved = 0
        lrc_skipped = 0
        lrc_failed = 0
        txt_saved = 0
        txt_skipped = 0
        txt_failed = 0
        purged = 0
        failed = 0
        if len(synced_lyrics) > 0:
            lrc_saved, lrc_skipped, lrc_failed = write_lrc_files(synced_lyrics, ".lrc", overwrite, progress, write_success)
        if len(unsynced_lyrics) > 0:
            txt_saved, txt_skipped, lrc_failed = write_lrc_files(unsynced_lyrics, ".txt", overwrite, progress, write_success)
        
        if log_to_disk:
            export_log(write_success, separate_logs, log_path)

        if delete:
            purged, failed = purge_tags(write_success, progress)
        
        print(f"\n{len(music_files)} music files processed, {len(synced_lyrics)} synced lyrics and {len(unsynced_lyrics)} unsynced lyrics found.")
        if lrc_saved > 0 or lrc_skipped > 0 or lrc_failed > 0:
            print(f"{lrc_saved} synced lyrics written to disk, {lrc_skipped} skipped, {lrc_failed} errors.")
        if txt_saved > 0 or txt_skipped > 0 or lrc_failed > 0:
            print(f"{txt_saved} unsynced lyrics written to disk, {txt_skipped} skipped., {txt_failed} errors.")
        if purged > 0 or failed > 0:
            print(f"Deleted embedded lyrics of {purged} files, encountered {failed} errors.")
        print("Closing in 5 seconds.")
        sleep(5)
        sys.exit()
        
if __name__ == "__main__":
    args = parse_arguments()
    try:
        main(args)
    except KeyboardInterrupt:
        print("Interrupted")
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)