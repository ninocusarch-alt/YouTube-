"""Live mode package.

The YouTube / Chrome-extension path is untouched. This package only replaces
"who feeds audio" and "who renders subtitles": a local WASAPI capture client
talks to the existing ``/ws/sessions/{id}`` endpoint, and a new hub broadcasts
final Chinese lines to an OBS overlay plus a streamer console.
"""
