#DASH Live Generator


### General
This DASH live generator generates live DASH content from VoD content or a capture of an interval of live content.
The generated live content is written to a target file system.

It requires Python 2.6 or later 2.x to run.

The input is DASH content in live-profile format. This may for example be a capture
of 15min of live segments.

### How it works
The livegenerator is started as

    python livedashgenerator.py [-v] configfile.cfg

It will then check the manifest to find the media segment directories and analyze all such segments
to find the start and end number for looping and if the durations and timing is good enough compared to the segmentDuration in the MPD (maximum deviation is 100ms).

Then a new manifest will be generated and it and the init segments will be written to disk.
A process is started that periodically generates media segments and removes segments older than the timeShiftBufferDepth as specified in the config file.
The media segments are updated with new values of segment number and tfdt to make
the output stream continuous and get the appropriate media presentation time (tfdt=0) for the first segments for each
media type. The number of the first output segment is the one specified as startNumber in the MPD being used as input.

The process can be stopped using Ctrl-C.

An example config file is available in `example.cfg`.

WebDav can be used as output as an alternative to local file system.

### Note
If there is an explicit <BaseURL> element in the input MPD, it must be edited to reflect the URL of the output directory.

