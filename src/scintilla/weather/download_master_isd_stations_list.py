#!/usr/bin/env python
"""
    download_master_isd_stations_list.py - download the CSV with all
    NOAA ISD weather stations into METADATA_DIR.

    usage: python download_master_isd_stations_list.py
"""

import requests

from scintilla.common.defines import ISD_HISTORY_URL, METADATA_DIR


def main(out_path=None):
    if out_path is None:
        out_path = METADATA_DIR / "isd_station_metadata.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(ISD_HISTORY_URL)
    response.raise_for_status()
    out_path.write_bytes(response.content)
    print(f"ISD station metadata downloaded successfully and written to {out_path}.")


if __name__ == "__main__":
    main()
