# Line Endings Utility

This tool scans a directory tree and reports line-ending counts for each regular file.
It walks recursively, skips any directory named `.git`, and does not follow symlinks.
Unreadable files and binary files are reported as `NONE`; the tool never modifies files.

Run it from the repository root with:

```sh
python3 tools/line_endings/line_endings.py <directory>
```

Output format:

```text
CLASS<TAB>crlf=<n><TAB>lf=<n><TAB>cr=<n><TAB>path
TOTAL<TAB>files=<n><TAB>mixed=<n>
```

Paths in the report are relative to the directory you pass in.
