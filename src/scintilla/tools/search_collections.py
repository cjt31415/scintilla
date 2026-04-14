#!/usr/bin/env python
"""
    search_collections.py - given a keyword or mission name (short-name), show summary or details
        short_names & versions needed in search_granules.py

"""
import argparse
import sys
from pprint import pprint

from earthaccess import DataCollections

from scintilla.common.utils import (
    aoi_area_in_km2,
    aoi_list,
    find_timespan,
    geometry_gdf_to_json,
    load_geometry,
    polygon_to_bbox,
)

# there are duplicate dataset names for anything that is both DAAC and cloud hosted
SKIP_CLOUD_DATACOLLECTIONS = True

def extract_data_formats(collection):
    if 'ArchiveAndDistributionInformation' not in collection['umm']:
        return 'unknown'

    dist_dict = collection['umm']['ArchiveAndDistributionInformation']
    if 'FileDistributionInformation' not in dist_dict:
        return 'unknown'

    file_dist_list = dist_dict['FileDistributionInformation']
    format_list = []

    try:
        for fd in file_dist_list:
            format_list.append(fd['Format'])
    except (KeyError, TypeError) as e:
        print(f"Something went wrong with final format extraction: {e}")
        return 'unknown'

    return ":".join(format_list)




def show_collection_summary(query, num_hits, max_items):
    num_gets = min(num_hits, max_items)
    collections = query.get(num_gets)

    if SKIP_CLOUD_DATACOLLECTIONS:
        print(f"start with {len(collections)}")
        collections = [col for col in collections if 'CLOUD' not in col['meta']['provider-id']]
        print(f"after filter by cloud {len(collections)}")

    bad_collections = []

    for collection in collections:
        try:
            start_dt, end_dt = find_timespan(collection)
            print(f"{collection['umm']['ShortName']:<40}\t{start_dt.strftime('%Y-%m')} - {end_dt.strftime('%Y-%m')}")
        except Exception as e:
            bad_collections.append(collection)
            print(f"  Error: {e}")

    if len(bad_collections) > 0:
        print(f"Had errors from {len(bad_collections)} collections")
        summaries = [collection.summary() for collection in bad_collections]
        for summary in summaries:
            pprint(summary)


def show_multiple_collection_details(query, num_hits, max_items, debug=False):
    num_gets = min(num_hits, max_items)
    collections = query.get(num_gets)

    if SKIP_CLOUD_DATACOLLECTIONS:
        print(f"start with {len(collections)}")
        collections = [col for col in collections if 'CLOUD' not in col['meta']['provider-id']]
        print(f"after filter by cloud {len(collections)}")

    for collection in collections:
        show_collection_details(collection, debug=debug)




def show_collection_details(collection, debug=False):

    if debug:
        print("Debug is on.")

    try:
        # there are two top-level keys in a collection: 'meta' and 'umm'
        # variables from 'meta':
        num_granules = collection['meta']['granule-count']
        concept_id = collection['meta']['concept-id']       # some searches use this
        provider_id = collection['meta']['provider-id']     # DAAC Name

        # variables from 'umm' (Unified Metadata Model)
        version = collection['umm']['Version']
        short_name = collection['umm']['ShortName']
        title = collection['umm']['EntryTitle']
        abstract = collection['umm']['Abstract']
        start_dt, end_dt = find_timespan(collection)
        formats = extract_data_formats(collection)

    except (KeyError, TypeError) as e:
        print(f"Couldn't access one of the desired fields: {e}")
        return

    print(" ")
    print(f"{'ShortName':<20}: {short_name}")
    print(f"{'Version':<20}: {version}")
    print(f"{'Title':<20}: {title}")
    print(f"{'StartDate':<20}: {start_dt.strftime('%Y-%m')}")
    print(f"{'EndDate':<20}: {end_dt.strftime('%Y-%m')}")
    print(f"{'Num Granules':<20}: {num_granules}")
    print(f"{'Concept-id':<20}: {concept_id}")
    print(f"{'Provider':<20}: {provider_id}")
    print(f"{'Data formats':<20}: {formats}")
    print(f"{'Abstract':<20}: {abstract}")
    print(" ")



def main(aoi=None,
        keyword=None,
        short_name=None,
        max_items=None,
        all_detail=False,
        debug=False):


    if not (keyword or short_name):
        print("You must specify one of keyword, or short_name; aoi is optional")
        sys.exit(1)

    # either search for a generic keyword (e.g. lightning) or by a mission short-name

    if aoi:
        aoi_gdf = load_geometry(aoi)
        if len(aoi_gdf) != 1:
            raise ValueError("This code only understands simple geometries")
        aoi_geom_json = geometry_gdf_to_json(aoi_gdf)   # this is just the {'type':'Polygon', 'coordinates': [[(), ()]]}

        area = aoi_area_in_km2(aoi_gdf)
        print(f"area of [{aoi}] AOI is approximately {round(area, 2)} km^2")
        bbox = polygon_to_bbox(aoi_geom_json)

        print("Warning: I don't think this is working correctly")
    else:
        bbox = None

    if short_name:
        if bbox:
            query = DataCollections().short_name(short_name).bounding_box(*bbox)
        else:
            query = DataCollections().short_name(short_name)
    elif keyword:
        if bbox:
            query = DataCollections().keyword(keyword).bounding_box(*bbox)
        else:
            query = DataCollections().keyword(keyword)
    else:
        print("Oops...")


    num_hits = query.hits()

    if num_hits == 0:
        print(f"{num_hits} data collections matching keyword {keyword}")
        sys.exit(-1)

    # go one of two ways depending on use of short_name
    if short_name:
        if num_hits == 1:
            collections = query.get()
            if len(collections) != 1:
                raise RuntimeError("Expected only one collection")
            collection = collections[0]
            show_collection_details(collection, debug=debug)
        elif all_detail:
            show_multiple_collection_details(query, num_hits, max_items, debug=debug)
        else:
            print(f"Oh, oh, using short_name {short_name} got {num_hits} hits - falling back to summary")
            print("Use --all-detail to override")
            show_collection_summary(query, num_hits, max_items)
    else:
        show_collection_summary(query, num_hits, max_items)




def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aoi', type=str, default=None, choices=aoi_list(), help='AOI name - to restrict by location (optional)')
    parser.add_argument('--keyword', type=str, default=None, help="What to search collections for (optional)")
    parser.add_argument('--short-name', type=str, default=None, help="If short-name is supplied then get more detail on just that one.")
    parser.add_argument('--max-items', type=int, default=100, help="total_count from stats less than this to do search")

    parser.add_argument('--all-detail', action='store_true', help='Show details of all collections even when more than one')
    parser.add_argument('--debug', action='store_true', help='enable detailed diagnostics')

    opt = parser.parse_args()
    return opt

if __name__ == "__main__":
    opt = parse_opt()
    main(**vars(opt))

