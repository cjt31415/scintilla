"""
    granule_utils.py - shared helpers for parsing earthaccess CMR granule
    metadata.

    Used by tools/get_granules.py, tools/search_granules.py,
    tools/get_rain_window_granules.py.
"""


def extract_download_url(granule):
    """Return the HTTPS 'GET DATA' URL from a CMR granule, or None."""
    for url_dict in granule['umm']['RelatedUrls']:
        if url_dict['Type'] == 'GET DATA':
            return url_dict['URL']
    return None


def extract_S3_download_url(granule):
    """Return the s3:// 'GET DATA VIA DIRECT ACCESS' URL from a CMR granule, or None."""
    for url_dict in granule['umm']['RelatedUrls']:
        if url_dict['Type'] == 'GET DATA VIA DIRECT ACCESS':
            return url_dict['URL']
    return None


def extract_begin_end_times(granule):
    """Return (BeginningDateTime, EndingDateTime) ISO strings from a CMR granule."""
    temp_extent_dict = granule['umm']['TemporalExtent']['RangeDateTime']
    return temp_extent_dict['BeginningDateTime'], temp_extent_dict['EndingDateTime']
