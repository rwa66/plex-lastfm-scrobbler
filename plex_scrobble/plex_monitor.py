#!/usr/bin/env python
import re
import os
import socket
import urllib2
import time
import xml.etree.ElementTree as ET
import logging
import shelve
import time

from lastfm import LastFm

MAX_CACHE_AGE = 5

class ScrobbleCache(object):

    def __init__(self, conf='/tmp/cache'):

        self.conf = conf
        self.cache = shelve.open(self.conf, writeback=True)
        self.logger = logging.getLogger(__name__)

    def add(self, key, value, cache_hit=1):

        self.logger.info('adding \'{key}\' \'{value}\' to retry cache.'.format(
            key=key, value=value))

        self.cache[str(time.time())] = [key, value, cache_hit]
        self.cache.sync()

    def remove(self, key):

        self.logger.info('removing \'{key}\': \'{artist}\' - \'{track}\' from retry cache.'.format(
            key=key, artist=self.cache[key][0], track=self.cache[key][1]))
        del self.cache[key]
        self.cache.sync()

    def close(self):
        self.cache.close()

    def items(self):
        for key in self.cache: 
            print '{key} : {artist} - {track}'.format(key=key,
                artist=self.cache[key][0], track=self.cache[key][1])

    def retry_queue(self):

        lastfm = LastFM(config)

        for key in self.cache:
            # do submissions retry
            try:
                lastfm.scrobble(self.cache[key][0], self.cache[key][1])
                self.cache[key][2] += 1  
            except:
                # remove this record from retry cache, if we're at the retry limit
                if self.cache[key][2] >= MAX_CACHE_AGE: 
                    logger.info('MAX_CACHE_AGE for {key} : {artist} - {track}'.format(
                        key, self.cache[key][0], self.key[1]))
                    self.remove(key)
                continue


def parse_line(l):
    ''' Matches based on a "got played" plex media server audio media object.  '''

    logger = logging.getLogger(__name__)

    played = re.compile(r".*\sDEBUG\s-\sLibrary\sitem\s(\d+)\s'.*'\sgot\splayed\sby\saccount.*")
    m = played.match(l)

    if m:
        logger.info('Found played song and extracted library id \'{l_id}\' from plex log '.format(l_id=m.group(1)))
        return m.group(1)


def fetch_metadata(l_id, config):
    ''' retrieves the metadata information from the PHT api. '''

    logger = logging.getLogger(__name__)
    url = '{url}/library/metadata/{l_id}'.format(url=config.get('plex-scrobble',
      'mediaserver_url'), l_id=l_id)
    logger.info('Fetching library metadata from {url}'.format(url=url))

    # fail if request is greater than 2 seconds.
    try:
        metadata = urllib2.urlopen(url, timeout=2)
    except urllib2.URLError, e:
        logger.error('urllib2 error reading from {url} \'{error}\''.format(url=url,
                      error=e))
        return False
    except socket.timeout, e:
        logger.error('Timeout reading from {url} \'{error}\''.format(url, error=e))
        return False

    tree = ET.fromstring(metadata.read())
    track = tree.find('Track')

    # if present use originalTitle. This appears to be set if
    # the album is various artist 
    artist = track.get('originalTitle')
    if not artist:
        artist = track.get('grandparentTitle')

    song = track.get('title')

    if not all((artist, song)):
        logger.warn('unable to retrieve meatadata keys for libary-id={l_id}'.
                format(l_id=l_id))
        return False

    return {'track': song, 'artist': artist}


def monitor_log(config):

    logger = logging.getLogger(__name__)

    try:
        f = open(config.get('plex-scrobble', 'mediaserver_log_location'))
    except IOError:
        logger.error('Unable to read log-file {0}. Shutting down.'.format(config.get(
          'plex-scrobble', 'mediaserver_log_location')))
        return
    f.seek(0, 2)

    while True:

        # reset our file handle in the event the log file was not written to
        # within the last 60 seconds. This is a very crude attempt to support
        # the log file i/o rotation detection cross-platform.
        if int(time.time()) - int(os.fstat(f.fileno()).st_mtime) >= 60 :
            logger.debug('Possible log file rotation, resetting file handle')
            f.close()
            f = open(config.get('plex-scrobble', 'mediaserver_log_location'))
            f.seek(0, 2)

        time.sleep(.05)
        line = f.readline()

        # read all new lines starting at the end. We attempt to match
        # based on a regex value. If we have a match, extract the media file
        # id and send it off to last.fm for scrobble.
        if line:
            played = parse_line(line)

            if not played: continue

            metadata = fetch_metadata(played, config)

            if not metadata: continue

            # submit to last.fm
            lastfm = LastFm(config)
            a = lastfm.scrobble(metadata['artist'], metadata['track'])

            if not a:
                cache = ScrobbleCache()
                cache.add({time: [metadata['artist'], metadata['track']]})
                cache.close