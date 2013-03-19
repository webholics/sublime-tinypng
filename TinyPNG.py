import sublime
import sublime_plugin
import os
import fnmatch
import threading
import json
from base64 import standard_b64encode

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, HTTPError, urlopen

TINYPNG_URL = 'http://api.tinypng.org/api/shrink'


class TinypngApiCall(threading.Thread):
    def __init__(self, png_file, api_key):
        self.png_file = png_file
        self.api_key = api_key
        self.error = None
        self.response = None
        threading.Thread.__init__(self)

    def run(self):
        result = None
        try:
            # make api request
            in_data = open(self.png_file, 'rb').read()
            raw_key = ('api:' + self.api_key).encode('ascii')
            enc_key = standard_b64encode(raw_key).decode('ascii')
            request = Request(TINYPNG_URL.encode('utf-8'), in_data)
            request.add_header('Authorization', 'Basic %s' % enc_key)
            request.add_header('Content-Type', 'application/octet-stream')

            result = urlopen(request)

            # download shrinked file
            self.response = json.loads(result.read().decode('utf8'))
            out_data = urlopen(self.response['output']['url']).read()
            if len(out_data) > 0:
                f = open(self.png_file, 'wb')
                f.write(out_data)

        except HTTPError as e:
            self.error = 'HTTP error %s contacting TinyPNG API' % (str(e.code))
            try:
                body = json.loads(e.read().decode('utf8'))
                self.error += ' (%s)' % body['message']
            except ValueError as e:
                pass


class TinypngCommand(sublime_plugin.WindowCommand):
    def run(self):

        # get API key
        settings = sublime.load_settings('TinyPNG.sublime-settings')
        api_key = settings.get('api_key')
        if not api_key:
            sublime.error_message('You need to set an API key for the TinyPNG service!\n(Preferences -> Package Settings -> TinyPNG)')
            return

        self.api_key = api_key

        # find all folders which contain a PNG file somewhere
        png_folders = set()
        for folder in self.window.folders():
            for root, dirnames, filenames in os.walk(folder):
                if len(fnmatch.filter(filenames, '*.png')) > 0:
                    while True:
                        png_folders.add(root)
                        if root == folder:
                            break
                        root, tail = os.path.split(root)

        self.png_folders = []
        for folder in png_folders:
            self.png_folders.append(folder)
        self.png_folders.sort()

        self.window.show_quick_panel(self.png_folders, self.select_folder_callback)

    def output(self, output, clear=False):

        if not hasattr(self, 'output_view'):
            self.output_view = self.window.get_output_panel('tinypng')
        self.output_view.set_read_only(False)

        edit = self.output_view.begin_edit()
        if clear:
            region = sublime.Region(0, self.output_view.size())
            self.output_view.erase(edit, region)
        self.output_view.insert(edit, self.output_view.size(), output)
        self.output_view.end_edit(edit)

        self.output_view.set_read_only(True)
        self.window.run_command('show_panel', {'panel': 'output.tinypng'})

    def select_folder_callback(self, index):
        # find all PNGs
        self.png_files = []
        for root, dirnames, filenames in os.walk(self.png_folders[index]):
            for filename in fnmatch.filter(filenames, '*.png'):
                self.png_files.append(os.path.join(root, filename))

        self.output('Are you sure you want to shrink ' + str(len(self.png_files)) + ' PNG file(s)?', True)

        options = [
            ['Yes', 'All selected PNG files will be overwritten!'],
            ['No', 'Aborts command.']
        ]
        self.window.show_quick_panel(options, self.confirmCallback)

    def confirmCallback(self, index):
        if(index > 0):
            self.window.run_command('hide_panel')
            return

        self.output('Shrinking ' + str(len(self.png_files)) + ' PNG file(s)', True)

        threads = []
        for pngFile in self.png_files:
            thread = TinypngApiCall(pngFile, self.api_key)
            threads.append(thread)

        self.handle_threads(threads)

    def handle_threads(self, available, running=[], finished=[]):
        # check running threads
        still_running = []
        for thread in running:
            if thread.is_alive():
                still_running.append(thread)
                continue

            finished.append(thread)
            self.output('.')

        # start new threads
        while len(still_running) < 5 and len(available) > 0:
            thread = available.pop()
            thread.start()
            still_running.append(thread)

        if len(still_running) > 0:
            sublime.set_timeout(lambda: self.handle_threads(available, still_running, finished), 100)
            return

        in_size = 0
        out_size = 0
        print(len(finished))
        for thread in finished:
            if thread.error:
                self.output(thread.error + '\n')
            elif thread.response:
                in_size += thread.response['input']['size']
                out_size += thread.response['output']['size']

        if(out_size > 0):
            self.output('\nReduced overall filesize by %.2f%%.' % ((1 - out_size / float(in_size)) * 100))
