# Test fixtures

`data/` is a miniature copy of the GAGNVÍST data release (cutoff 2026-10-18): six real
tables, each in Icelandic and English, copied byte for byte with the release's folder
layout, plus a matching `catalogue.csv` and `SHA256SUMS.txt`.

| Table | Cells | Why it is here |
|---|---:|---|
| SAM91452 | 9 | one bilingual px file served to both languages; encoding ISO-8859-15 |
| KOS02105 | 12 | encoding Windows-1252; the "not applicable" marker `.` |
| HEI11505 | 104 | the markers `-` (exactly zero), `.` and `..` (not available) |
| KOS07112 | 360 | dimensions in a different order in each language |
| VIS13401 | 8 | the px file starts with a UTF-8 byte-order mark |
| HEI02601 | 28 | metadata.json has no title (the API leaves it out for some tables) |

Source: Statistics Iceland (Hagstofa Íslands), CC BY 4.0.
These files are marked binary in `.gitattributes` so git never changes their bytes.
