# YouTube_RSS

YouTube\_RSS is a simple YouTube client I've made for fun. The goal is to have a simple
user interface for those who want to preserve their privacy when using YouTube, but who
still want to be able to keep track of their favourite channels, etc.

YouTube\_RSS manages subscriptions to channels using RSS, rather than YouTube's
internal subscription system that requires a privacy violating Google account.

## Acknowledgement

> SimonDaNinja/youtube_rss - a set of tools for supporting development of anonymous RSS-based YouTube client applications.
> Copyright (C) 2021  Simon Liljestrand
> Contact by email: simon@simonssoffa.xyz

## Dependencies

The following python modules are used and may need to be installed, e.g. using pip:

```
feedparser
urllib3
pysocks
```

If you want to get thumbnails for videos, you will additionally need to install the
module `ueberzug`, e.g. using pip.

### MPV & YouTube-DL

MPV and YouTube-DL are used to stream the video, ao. 2022 YT-DLP is a superior
choice to YouTube-DL, which may suffer buffering issues. MPV will automatically
use YT-DLP if it is installed, otherwise falling back to YT-DL.

#### Ubuntu

```commandline
sudo apt-get install mpv
```

[Install yt-dlp](https://github.com/yt-dlp/yt-dlp#installation=)

#### Windows

```commandline
choco install mpv
choco install yt-dlp
```


## Usage

```commandline
python -m youtube_rss
```

## Disclaimer

Note that while I am enthusiastic about privacy and security,
I am not a professional, and may have missed something important. However, the surface to protect
should be relatively small, and I've taken care to get rid of DNS-leaks, etc. as well as I can.
If you are more knowledgable than I, then I would appreciate input on how to make YouTube\_RSS
more privacy preserving and secure.

# Manual
Most of the way the application works is self-explanatory; I won't tell you that to search for a
video, you enter the "search for video" option (although I guess I just did), but rather focus on
the things not immediately obvious when opening the program.

## Key binds
The keybindings are designed so that the user can do almost everything necessary by just
using the arrow keys (except, of course, when writing search queries), or by using the
`hjkl` keys for vi users.

When in a menu, the user can press `KEY_UP` or `k` to move to the previous menu item.

When in a menu, the user can press `KEY_DOWN` or `j` to move to the next menu item.

When in a menu, the user can press `g` (lower case) to go to the first menu item.

When in a menu, the user can press `G` (upper case) to go to the last menu item.

When in a menu, the user can type a number and then press either `Enter` or `l` or `KEY_RIGHT`
to jump to the item indicated by the number typed by the user.

When in a menu, the user can press `ENTER`, `l` or `KEY_RIGHT` to select the highlighted item, if no
number has been typed since last jump.

When in a menu, the user can press `q`, `<Ctrl>-C`, `h` or `KEY_LEFT` to go back to the previous menu.

When browsing subscriptions, in the menu where channels are displayed as menu items, the user can press
`a` to toggle all entries of the currently highlighted channel as seen or unseen

When browsing subscriptions, in the menu where videos from a particular channel are displayed as menu
items, the user can press `a` to toggle the highlighted entry as seen or unseen

## Thumbnails
Thumbnails are disabled by default. If you want to view video thumbnails, you need to run
YouTube\_RSS with the option `--use-thumbnails`. If you intend to do this in the long run,
you might want to alias it into the base command.

Thumbnail support is still a bit new and experimental, so for now, use it at your own
risk. The main concern to keep in mind is that thumbnail files will take up additional
storage.

## Files managed by the program
The database file that is used to keep track of subscriptions is saved under `~/.youtube_rss/database`,
and is formated as json.

If you are using thumbnails, thumbnail files are stored under `~/.youtube_rss/thumbnails/`
