import subprocess
import re
import base64
import requests
from pyfzf.pyfzf import FzfPrompt
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import unquote
import time 
import os

class VidSrcExtractor:
    def decode(self, str) -> bytearray:
        key_bytes = bytes('8z5Ag5wgagfsOuhz', 'utf-8')
        j = 0
        s = bytearray(range(256))

        for i in range(256):
            j = (j + s[i] + key_bytes[i % len(key_bytes)]) & 0xff
            s[i], s[j] = s[j], s[i]

        decoded = bytearray(len(str))
        i = 0
        k = 0

        for index in range(len(str)):
            i = (i + 1) & 0xff
            k = (k + s[i]) & 0xff
            s[i], s[k] = s[k], s[i]
            t = (s[i] + s[k]) & 0xff
            decoded[index] = str[index] ^ s[t]

        return decoded

    def decode_base64_url_safe(self, s) -> bytearray:
        standardized_input = s.replace('_', '/').replace('-', '+')
        binary_data = base64.b64decode(standardized_input)

        return bytearray(binary_data)

    def decrypt_source_url(self, source_url) -> str:
        encoded = self.decode_base64_url_safe(source_url)
        decoded = self.decode(encoded)
        decoded_text = decoded.decode('utf-8')

        return unquote(decoded_text)
    
    def int_2_base(self, x, base) -> str:
        charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"

        if x < 0:
            sign = -1
        elif x == 0:
            return 0
        else:
            sign = 1

        x *= sign
        digits = []

        while x:
            digits.append(charset[int(x % base)])
            x = int(x / base)
        
        if sign < 0:
            digits.append('-')
        digits.reverse()

        return ''.join(digits)
    
    def unpack(self, p, a, c, k, e=None, d=None) -> str:
        for i in range(c-1, -1, -1):
            if k[i]: p = re.sub("\\b"+self.int_2_base(i,a)+"\\b", k[i], p)
        return p
    
    def key_permutation(self, key, data) -> str:
        state = list(range(256))
        index_1 = 0

        for i in range(256):
            index_1 = ((index_1 + state[i]) + ord(key[i % len(key)])) % 256
            state[i], state[index_1] = state[index_1], state[i]

        index_1 = index_2 = 0
        final_key = ''

        for char in range(len(data)):
            index_1 = (index_1 + 1) % 256
            index_2 = (index_2 + state[index_1]) % 256
            state[index_1], state[index_2] = state[index_2], state[index_1]

            if isinstance(data[char], str):
                final_key += chr(ord(data[char]) ^ state[(state[index_1] + state[index_2]) % 256])
            elif isinstance(data[char], int):
                final_key += chr((data[char]) ^ state[(state[index_1] + state[index_2]) % 256])

        return final_key
    
    def encode_id(self, v_id) -> str:
        key1, key2 = requests.get('https://raw.githubusercontent.com/Claudemirovsky/worstsource-keys/keys/keys.json').json() # love u claude
        decoded_id = self.key_permutation(key1, v_id).encode('Latin_1')
        encoded_result = self.key_permutation(key2, decoded_id).encode('Latin_1')
        encoded_base64 = base64.b64encode(encoded_result)

        return encoded_base64.decode('utf-8').replace('/', '_')
    
    def get_futoken(self, key, url) -> str:
        req = requests.get("https://vidplay.site/futoken", {"Referer": url})
        fu_key = re.search(r"var\s+k\s*=\s*'([^']+)'", req.text).group(1)
        
        return f"{fu_key},{','.join([str(ord(fu_key[i % len(fu_key)]) + ord(key[i])) for i in range(len(key))])}"
    
    def handle_vidplay(self, url) -> str:
        key = self.encode_id(url.split('/e/')[1].split('?')[0])
        subtitles_url = unquote(url.partition("?sub.info=")[-1].partition("&t=")[0])
        data = self.get_futoken(key, url)
        
        req_1 = requests.get(subtitles_url)
        subtitles = {subtitle.get("label"): subtitle.get("file") for subtitle in req_1.json()}

        req_2 = requests.get(f"https://vidplay.site/mediainfo/{data}?{url.split('?')[1]}&autostart=true", headers={"Referer": url})
        req_2_data = req_2.json()

        if type(req_2_data.get("result")) == dict:
            return req_2_data.get("result").get("sources"), subtitles
        return None

    def handle_filemoon(self, url) -> str:
        req = requests.get(url)
        matches = re.search(r'return p}\((.+)\)', req.text)
        processed_matches = []

        if not matches:
            raise Exception("No values found")
        
        split_matches = matches.group(1).split(",")
        corrected_split_matches = [",".join(split_matches[:-3])] + split_matches[-3:]
        
        for val in corrected_split_matches:
            val = val.strip()
            val = val.replace(".split('|'))", "")
            if val.isdigit() or (val[0] == "-" and val[1:].isdigit()):
                processed_matches.append(int(val))
            elif val[0] == "'" and val[-1] == "'":
                processed_matches.append(val[1:-1])

        processed_matches[-1] = processed_matches[-1].split("|")
        unpacked = self.unpack(*processed_matches)
        hls_url = re.search(r'file:"([^"]*)"', unpacked).group(1)
        return hls_url, None
        

    def get_source_url(self, source_id) -> str:
        req = requests.get(f"https://vidsrc.to/ajax/embed/source/{source_id}")
        data = req.json()

        encrypted_source_url = data.get("result", {}).get("url")
        return self.decrypt_source_url(encrypted_source_url)

    def get_sources(self, data_id) -> dict:
        req = requests.get(f"https://vidsrc.to/ajax/embed/episode/{data_id}/sources")
        data = req.json()

        return {video.get("title"): video.get("id") for video in data.get("result")}

    def get_vidsrc_stream(self, source_name, vidurl) -> Optional[str]:

        print(f"Requesting...")
        req = requests.get(vidurl)

        if req.status_code == 404:
            return None
        
        soup = BeautifulSoup(req.text, "html.parser")
        sources_code = soup.find('a', {'data-id': True}).get("data-id")
        sources = self.get_sources(sources_code)
        source = sources.get(source_name)
        if not source:
            print(f"No source found for {source_name}")
            return

        source_url = self.get_source_url(source)
        if "vidplay" in source_url:
            return self.handle_vidplay(source_url)
        elif "filemoon" in source_url:
            return self.handle_filemoon(source_url)
        
def shorten_url(url):
    api_url = f"http://tinyurl.com/api-create.php?url={url}"
    response = requests.get(api_url)
    return response.text

def ply(video_url, subtitle_url=None, platform='windows'):

    try:
        if platform in 'windows':
            mpv_path = r"C:\mpv\mpv.exe"
            command = f"\"{mpv_path}\" --fs \"{video_url}\""
            if subtitle_url:
                command += f" --sub-file=\"{subtitle_url}\""
            subprocess.Popen(command)
            
        elif platform == 'linux':
            command = f"mpv --fs \"{video_url}\""
            if subtitle_url:
                command += f" --sub-file=\"{subtitle_url}\""
            subprocess.Popen(command,shell=True)

        elif platform == 'mac':
            command = f"mpv --fs \"{video_url}\""
            if subtitle_url:
                command += f" --sub-file=\"{subtitle_url}\""
            subprocess.Popen(command)

        elif platform == 'android':
            # Android mpv might not support external subtitles via command line
            command = ["am", "start", "-n", "is.xyz.mpv/is.xyz.mpv.MPVActivity", "-e", "filepath", video_url]
            subprocess.Popen(command)

        elif platform == 'iphone':
            format_video_url = video_url.replace("#.mp4","")
            vlc_url = f"vlc://{format_video_url}"
            short_url = shorten_url(vlc_url)
            print(f"\033]8;;{short_url}\033\\-------------------------\n- Tap to open -\n-------------------------\033]8;;\033\\\n")
            input("Press Enter to continue...")
            
        print("Playing, please wait...")

    except Exception as e:
        print("[!] Please install player, Error occurred:", e)

def select_platform():
    fzf = FzfPrompt()
    options = ['windows', 'linux', 'mac', 'iphone', 'android']
    print("Select your platform:")
    return fzf.prompt(options)[0]

def select_subtitle(subtitles):
    fzf = FzfPrompt()
    subtitle_keys = list(subtitles.keys())
    return subtitles[fzf.prompt(subtitle_keys)[0]]

def vid_parser_m(vidurl):
    vsc = VidSrcExtractor()
    result = vsc.get_vidsrc_stream("Vidplay", vidurl)

    if not result:
        print("[!] Video not found")
        return

    streams, subtitles = result
    streaming_link = streams[0].get("file") if streams else None
    subtitle_link = None

    if subtitles:
        subtitle_link = select_subtitle(subtitles)

    platform = select_platform()
    ply(streaming_link, subtitle_link, platform)

if __name__ == "__main__":
    vid_parser_m()