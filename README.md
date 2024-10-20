# lyrict
## Python script to recursively check, standardize, import and export embedded and external synced and unsynced lyrics of audio files.

I initially wrote this as a testing tool to find unlinked .lrc files in my music library. The only link between .lrc and audio files is an identical base name. When audio files are automatically renamed through software but the .lrc files are not, this link can break.<br>
In test mode, the script will recursively scan a given directory for .lrc files (synced lyrics) and .txt files (unsynced lyrics). It then finds matching music files (default: flac and mp3) and logs those .lrc and .txt files without matching audio files as unlinked. It can also log all matches (sorted by filetype) as lists of paths to disk in case these are wanted for further processing in other software.

Later on I added another mode that utilizes [Mp3tags](https://www.mp3tag.de/en/) (limited) cli functionality to open all audio files that do have synced or unsynced external lyrics in Mp3tag (Windows/Mac only). The mp3tag mode can create actions for Mp3tag that allow an easy way to back up existing embedded lyrics, embed the external lyrics and then delete the previously created backups.<br>
This mode is customizable and flexible concerning the used tags and only limited by Mp3tags internal mappings and supported tags.<br>
However Mp3tag does not support the SYLT frame of mp3 files, where synced lyrics are saved as per specification and exporting lyrics from within Mp3tag to external lyrics is also not easily done. This mode also cannot delete the external lyrics files after embedding them.

Which led me to create the third mode, export mode. Export mode uses [mutagen](https://mutagen.readthedocs.io/en/latest/) to scan all audio files in a given directory for embedded lyrics, both synced and unsynced, and can then export these tags to external .lrc and .txt files. This mode does support both LYRICS and UNSYNCEDLYRICS vorbis tags (flac files) and SYLT and USLT frames (mp3 files). For mp3 files it also exports the vorbis tag LYRICS as some people prefer it over the restrictive SYLT frame. It can also purge the existing embedded lyrics after a successful export.

The latest addition was a fourth mode, import mode. Import mode also uses mutagen to import .lrc and .txt lyrics into flac and mp3 files and is currently rigid. For flac files it uses LYRICS/UNSYNCEDLYRICS vorbis tags and for mp3 files it uses the SYLT/USLT frames to embed lyrics. It can delete the external lyrics files after a successful import.

Both the export mode and the import mode also support fixing/standardizing of lrc timestamps (optional). There are many different timestamp formats:<br>
`[mm:ss.xx] text`, `[m:ss.xxx]text`, `[mmm:ss.xxx]`, `[hh:mm:ss.xxx]`, `[mm:ss]` just to name a few.
I decided to detect all of these versions (and mixes between them) and tidy them up/fix them:<br>
The script does try to respect the source format.<br>
`[62:00.000]text` becomes `[01:02:00.000]text` to correctly represent the hours while
`[03:20]` remains `[03:20]` as adding 3 zeros to it would give no extra precision and simply wastes space.
When the script has to create timestamps (when exporting from sylt), it will always choose `[mm:ss.xxx]lyrics` for timestamps without hours and `[hh:mm:ss.xxx]lyrics` for those with hours.

All modes support logging and can show progress bars for most of the steps.

## Modes

**What can the test mode do?**
  * recursively scan for .lrc and .txt files in a given directory
  * look for audio files with a matching base name (extensions can be specified, default: flac & mp3)
  * log unlinked .lrc and .txt files as well as linked music files to disk
  
**What can the mp3tag mode do?**
  * everything the test mode does plus:
  * open only music files with linked external lyrics in Mp3tag
  * create action for Mp3tag to back up existing embedded lyrics
  * create actions for Mp3tag to embed external lyrics, both .lrc and .txt (overwrites embedded lyrics)
  * create action for Mp3tag to delete previously created lyrics backup
  * supports all tags and audio formats that Mp3tag does (for better and for worse)
  
**What can the import mode do?**
  * everything the test mode does plus:
  * embed external synced and unsynced lyrics into flac and mp3 files (skip existing or purge and overwrite existing lyrics)
  * currently supported tags: vorbis LYRICS, UNSYNCEDLYRICS for flac and id3 frames: SYLT, USLT for mp3
  * standardize and fix timestamps of synced lyrics to `[mm:ss.xxx]text`, `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` formats (depending on their source format) (optional, flac only, as SYLT uses different formatting)
  * apply an offset from the `[offset:+-ms]` tag when importing to SYLT to achieve accurate timestamps
  * detect and properly split repeated lines `[02:05.300][02:15.100]chorus` when importing to SYLT
  * set the language of the embedded lyrics when it is present as `[la:language-code]` within the first 20 lines of the lyrics file
  * log the file path and lines that cannot be imported to SYLT
  * delete external lyrics files after a successful import
  * log results to disk

**What can the export mode do?**
  * recursively scan for music files with embedded lyrics in a given directory (extensions can be specified, default: flac & mp3)
  * export embedded lyrics to external .lrc and .txt files (skip existing or overwrite)
  * update/create [la:languagecode] tag based on the language tag of the embedded lyrics
  * currently supported tags: vorbis: LYRICS, UNSYNCEDLYRICS for flac files, vorbis: LYRICS + id3 frames: SYLT, USLT for mp3 files
  * standardize and fix timestamps of synced lyrics to `[mm:ss.xxx]text`, `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` formats (depending on their source format)
  * purge embedded tags after a successful export
  * log results to disk

## How to install lyrict

### Prerequisites

**Required:**
1. [python](https://www.python.org/downloads/) must be installed (tested with python 3.12.3)

**Optional:**
1. when using `-p` to show progress bars, [tqdm](https://github.com/tqdm/tqdm) must be installed, I used `pip3 install tqdm`
2. when using `-m mp3tag` as mode, [Mp3tag](https://www.mp3tag.de/en/) must be installed and on PATH
3. when using `-m import` or `-m export` as mode, [mutagen](https://mutagen.readthedocs.io/en/latest/) must be installed, I used `pip3 install mutagen`

If Mp3tag is not on PATH, the script will complain and (if on Windows) open the environment variables settings with instructions on how to add it to PATH.

### Downloading the script

You can either download/clone the entire repository and extract "lyrict.py" or you can copy the raw contents of lyrict.py, paste them into a .py file and save it that way.
If you want to be able to call it from anywhere on your system (which is more convenient than supplying a path via -d), you can add it to your PATH.

## Usage

### Output from -h:

```
usage: lyrict.py [-h] [-d [DIRECTORY]] [--delete] [-e EXTENSIONS [EXTENSIONS ...]] [--export] [-l]
                 [--log_path [LOG_PATH]] -m {export,import,mp3tag,test} [-o] [-p] [-s] [--standardize]

Test .lrc and .txt lyrics for broken links, embed synced and unsynced lyrics into tags or extract them from tags to
files.

options:
  -h, --help            show this help message and exit
  -d [DIRECTORY], --directory [DIRECTORY]
                        Test, Import, mp3tag: The directory to scan for .lrc and .txt files. Export: Directory to scan
                        for music files.
  --delete              Import: After successful import, deletes external .lrc and .txt files from disk. Export: After
                        successful export, deletes LYRICS, SYLT and USLT tags from mp3 files and LYRICS and
                        UNSYNCEDLYRICS tags from flac files.
  -e EXTENSIONS [EXTENSIONS ...], --extensions EXTENSIONS [EXTENSIONS ...]
                        Test, Import, mp3tag: List of song extensions the script will look for, default: flac and mp3.
                        Export: Song extensions that will be scanned for embedded lyrics, default flac and mp3
  --export              Export embedded lyrics of flac and mp3 files. Synced lyrics (LYRICS, SYLT) to .lrc and
                        unsynced lyrics (UNSYNCEDLYRICS/USLT) to .txt files. Requires mutagen, use "pip3 install
                        mutagen" to install it
  -l, --log             Test, mp3tag: Log filepaths (lyric and music extension) to "lyrict_results.log". "-ll" logs
                        each filetype separately (lrc_flac.log, txt_mp3.log...) instead. Import, Export: log
                        embedding/exporting results to "lyrict_import_results"/"lyrict_export_results"
  --log_path [LOG_PATH]
                        The directory to save logs to when used with -l or -ll, defaults to "."
  -m {export,import,mp3tag,test}
                        Mode, use 'test' to only log linked/unlinked songs to console or to file(s) when used with -l
                        or -ll. Use 'mp3tag' to embed external lyrics (.txt/.lrc) in audio tags via mp3tag. Use
                        'import' to embed external lyrics (.txt/.lrc) in audio tags via mutagen. Use 'export' to
                        export embedded tags to external files (.lrc/.txt) via mutagen.
  -o, --overwrite       mp3tag: Overwrite/recreate the mp3tag actions to reflect changes made in the config section.
                        Import: Purge and overwrite existing embedded lyrics tags (LYRICS/UNSYNCEDLYRICS/SYLT/USLT)
                        Export: Overwrite the content of existing .lrc/.txt files.
  -p, --progress        Show progress bars. Useful for huge directories. Requires tqdm, use "pip3 install tqdm" to
                        install it.
  -s, --single_folder   Test, Import, mp3tag: Only scans a single folder for .lrc and .txt files, no subdirectories.
                        Export: Only scans a single folder for music files.
  --standardize         Import/Export: standardize and fix timestamps of synced lyrics to `[mm:ss.xxx]text`,
                        `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` formats (depending on their source
                        format)
```

### More elaborate explanations of the modes and arguments:

**When called with -m test**<br>
**Test Mode:**<br>
This mode scans a directory and all subdirectories for .lrc and .txt files.<br>
The .txt files are filtered to match a common music file naming scheme: 2 or 3 digits followed by a space at the start of the filename. "01 Hello.flac" for example. This prevents matching info.txt and many other .txt files that are not unsynced lyrics. If your naming differs you have to adjust the regular expression as described in the "How to tweak behavior" section.<br>
Then this mode tries to find matching audio files, testing all extensions passed with -e, --extensions (default flac, mp3).<br>
Per default only unlinked songs (where no match was found) are logged to console.

**When called with -m mp3tag**<br>
**mp3tag Mode (requires Mp3tag, Windows/Mac only):**<br>
This does everything that Test Mode does and then opens only the songs with linked external lyrics in Mp3tag. Before that it checks if Mp3tag is on PATH and instructs the user on how to add it to PATH if it is not.<br>
Then it asks to create 4 actions for Mp3tag. They can back up existing embedded lyrics, embed .lrc files and .txt files to audio tags and lastly delete previously created backups.  
Both the names of the actions that will be created and the tags the actions should backup and embed to, are configurable in the CONFIG section at the top of the script. The default tag for synced lyrics is the vorbis tag LYRICS, for unsynced lyrics the default tag is UNSYNCEDLYRICS which Mp3tag internally maps to the USLT frame for mp3 files.<br>
When using this mode you have to be aware of the **internal mappings** of Mp3tag to ensure that the tags end up what you want them to be.<br>
The SYLT frame for example is **not supported** in Mp3tag, therefore synced lyrics will also be embedded to the LYRICS vorbis tag for mp3 files.<br>
The actions in Mp3tag will always overwrite existing embedded tags. They also cannot delete the external lyrics files after embedding them.

**When called with -m import**<br>
**Import Mode (requires mutagen):**<br>
This does everything that Test Mode does and then uses mutagen to embed external .lrc and .txt files to audio tags.  
Currently this mode is rigid and only supports embedding the vorbis tags LYRICS and UNSYNCEDLYRICS to flac files and the id3 frames SYLT and USLT to mp3 files.  
When -o, --overwrite is specified, existing embedded lyrics are purged and then written anew.  
When --delete is specified, the script will delete only those .lrc and .txt files that were embedded into an audio file.  
--standardize will fix and standardize the timestamps of the lyrics depending on their source formatting.
Both at the start of the line `[mm:ss.xxx]normal lyrics line` and within a line `[mm:ss.xxx]words<mm:ss.xxx> synced<mm:ss.xxx> line`.
It will also remove whitespace following a closing bracket `] `.
**BEWARE**: SYLT frames are very strict concerning the formatting.  
Lines in .lrc files that do not start with a timestamp (or multiple for repeated lines) are not stored in the SYLT frame and **will be lost**.
With `-l` or `-ll`, such omitted lines will be logged with the line number and the file path.
So DO check the logs before using `--delete` as that would result in permanently losing the information that cannot be embedded to the SYLT frame of mp3s.
These limitations only apply when embedding .lrc files into the SYLT frame of .mp3 files.

**When called with -m export**<br>
**Export Mode (requires mutagen):**<br>
This mode scans a directory and all subdirectories for audio files specified with -e, --extensions (default flac, mp3).<br>
It then uses mutagen to check if the audio files have embedded lyrics. Flac files are scanned for the vorbis tags LYRICS and UNSYNCEDLYRICS and mp3 files are scanned for the vorbis tag LYRICS as well as the id3 frames SYLT and USLT.<br>
Next, the script uses mutagen to export the synced and unsynced lyrics to .lrc and .txt files.<br>
When -o, --overwrite is not specified, existing external lyrics are skipped, otherwise they will be overwritten.<br>
When --delete is specified, the embedded lyrics tags of files where the export was successful (saved/skipped) will be purged.<br>
--standardize will fix/change the timestamp formatting of the resulting lrc files to `[00:00.000]TEXT`.

**-d, --directory PATH (optional, default=".")**<br>
When run without -d, the script will be called in the folder it was executed from.<br>
If -d is supplied, it must be followed by a valid path to a directory, which will be scanned for .lrc/.txt or audio files, depending on the mode.

**--delete (optional, destructive)**<br>
When used in import mode, successfully embedded external lyrics will be deleted.<br>
When used in export mode, successfully exported embedded lyric tags will be purged.

**-o, --overwrite (optional, destructive)**<br>
When used in import mode, purges and then recreates embedded lyrics.<br>
When used in export mode, overwrites existing .lrc and .txt files.

**--standardize (optional)**<br>
When used in import mode, the timestamps for synced lyrics that will be imported to the vorbis tag LYRICS will be reformatted to `[mm:ss.xxx]text`, `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` (depending on their source format). Timestamps within lines `[mm:ss.xxx]text<mm:ss.xxx> text<mm:ss.xxx> text` and repeated timestamps `[02:05.300][02:15.100]text` are also fixed. Lines that do not contain timestamps will be carried over as they are. Since the SYLT frame uses a different format, it is not affected by this standardization as all detected timestamps are converted to miliseconds.<br>
When used in export mode, the timestamps formatting for .lrc files will be reformatted to `[mm:ss.xxx]text`, `[hh:mm:ss.xxx]text`, `[mm:ss]text` or `[hh:mm:ss]text` (depending on their source format). Timestamps within lines `[mm:ss.xxx]text<mm:ss.xxx> text<mm:ss.xxx> text` and repeated timestamps `[02:05.300][02:15.100]text` are also fixed. Lines that do not contain timestamps will be carried over as they are.

**-s, --single_folder (optional)**<br>
Changes the behaviour of the script to be non-recursive. Only the directory specified with -d will be scanned.

**-l, --log**<br>
Depending on the mode, either linked/unlinked paths to audio files will be logged (test mode/mp3tag mode) or the results of an import/export will be logged (import mode/export mode).

**-p, --progress (optional)**<br>
Show progress bars during scanning, matching, embedding and exporting. Useful for huge directories.


## Common examples

### Case 1: test mode, searching for external lyrics with broken links:
* minimal version, recursively scan and only log unlinked .lrc/.txt files to console<br>
`lyrict.py -m test`

* log to combined logs<br>
`lyrict.py -m test -l`
  
* log to combined logs and show progress bars<br>
`lyrict.py -m test -lp`

* log to combined logs, show progress bars, specify a directory to scan and extensions to match<br>
`lyrict.py -m test -lp -d "D:\Test" -e flac mp3 ogg m4a`

### Case 2: mp3tag mode, opening linked songs in Mp3tag to embed lyrics:
* log unlinked lyrics to console, open linked songs in Mp3tag<br>
`lyrict.py -m mp3tag`

* log to combined logs and open linked songs in Mp3tag<br>
`lyrict.py -m mp3tag -l`
  
* overwrite/recreate Mp3tag actions and show progress bars<br>
`lyrict.py -m mp3tag -op`

* show progress bars, specify a directory to scan and extensions to match<br>
`lyrict.py -m mp3tag -p -d "D:\Test" -e flac mp3 ogg m4a`

### Case 3: import mode, embed external lyrics in flac and mp3 files:
* embed synced and unsynced external lyrics recursively, skip if embedded lyrics already exist<br>
`lyrict.py -m import`

* log results to disk<br>
`lyrict.py -m import -l`
  
* overwrite embedded lyrics and show progress bars<br>
`lyrict.py -m import -op`

* overwrite embedded lyrics, show progress bars and delete external lyrics that were embedded, specify a directory<br>
`lyrict.py -m import -op --delete -d "D:\Test"`

### Case 4: export mode, extract embedded lyrics and write them to .lrc and .txt files:
* export embedded synced and unsynced lyrics to .lrc and .txt files, skip existing<br>
`lyrict.py -m export`

* log results to disk<br>
`lyrict.py -m export -l`

* overwrite external lyrics and show progress bars<br>
`lyrict.py -m export -op`

* overwrite external lyrics, show progress bars and purge embedded lyrics that were exported, specify a directory<br>
`lyrict.py -m export -op --delete -d "D:\Test"`

## How to tweak behavior

* If you want to change the Mp3tag action names or the tags used for synced and unsynced lyrics in Mp3tag, modify the config section at the top of the script.

* During scanning, if your music files are named in a different pattern than "01 Hello.flac", you can edit the regular expression in this line to change the .txt matching:<br>
`pattern = r'^\d{2,3}\s'` replacing the regex with `r'^\d{2,3}_'` for example would match "01_Hello.flac" instead of "01 Hello.flac".

* During import, if you want to save the mp3 tags as id3 2.4 instead of id3 2.3 (chosen for compatibility), you can edit this line:<br>
`audio.save(v2_version=3)` and change `v2_version=3` to `v2_version=4`.

## Known Issues
 * During export, when an mp3 file has both the vorbis tag LYRICS and a SYLT frame, only one of them is written to an .lrc file. The other one is skipped. If -o, --overwrite is used, instead of being skipped, the first value will be overwritten with the second value. If LYRICS and SYLT have identical content, this should not matter. It could matter if SYLT contains less than LYRICS. Check when in doubt.

 * During export, when an mp3 file and a flac file with identical path and basename both have synced or unsynced lyrics embedded, only the lyrics of one of them will be written to .lrc and .txt, the other one will be skipped or overwritten if -o, --overwrite is used. Assuming that they are the same song with identical lyrics, this should also not matter.
 
 * Mp3tag does not support the SYLT frame. This means that when performing certain actions on mp3 files containing a SYLT frame in Mp3tag, that frame can be lost. (removing the tags and then undoing that step for example deletes the SYLT frame as it is not written back).
 
 * During import, when embedding synced lyrics from .lrc files to SYLT frames in mp3 files, any lines that do not begin with a timestamp WILL BE LOST. This is a limitation of the SYLT frame.
 
 * I've changed a couple dozen lines of code over the last few days and have not yet tested every possible combination of arguments. Consider this script a beta version at best, only use it on copies of your files or at the very least have an up-to-date backup of your files before using it. Also verify the results! I won't be responsible for lost lyrics.

