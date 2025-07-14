import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp
import os
import threading
from PIL import Image, ImageTk
import requests
from io import BytesIO
import time
import logging
import queue
import sys
import subprocess
import shutil
import re
from contextlib import contextmanager

# --- Path and Environment Setup ---
def get_ffmpeg_path():
    """ Find the path to ffmpeg executable. """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        ffmpeg_path = os.path.join(base_path, 'ffmpeg.exe')
        if os.path.exists(ffmpeg_path):
            return ffmpeg_path
    # Fallback to system ffmpeg
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
    # Additional paths to check
    possible_paths = [
        '/usr/local/bin/ffmpeg',
        '/usr/bin/ffmpeg',
        os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffmpeg.exe')
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

FFMPEG_PATH = get_ffmpeg_path()
if FFMPEG_PATH:
    ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
    if ffmpeg_dir not in os.environ['PATH']:
        os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']

# Configure logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
DEFAULT_DOWNLOAD_FOLDER = os.path.expanduser("~/Downloads")
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

# --- Global Variables ---
download_queue = queue.Queue()
details_queue = queue.Queue()
active_downloads = {}

# --- Timeout Context Manager (Unix-only) ---
@contextmanager
def timeout(seconds):
    """ Context manager for setting a timeout (Unix only). """
    if sys.platform != "win32":
        import signal
        def handler(signum, frame):
            raise TimeoutError("Operation timed out")
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
    else:
        yield  # No timeout support on Windows

class DownloadTask:
    def __init__(self, master, url, folder, quality_format, is_playlist, info_dict):
        self.master = master
        self.url = url
        self.folder = folder
        self.quality_format = quality_format
        self.is_playlist = is_playlist
        self.info_dict = info_dict
        self.cancel_flag = False
        self.start_time = None
        self.task_id = id(self)
        self.filepath = None

        self._create_ui()
        self.start_download()

    def _create_ui(self):
        self.frame = ctk.CTkFrame(self.master, corner_radius=10)
        self.frame.pack(fill="x", pady=10, padx=5)

        title = self.info_dict.get('title', 'Unknown Title')
        self.title_label = ctk.CTkLabel(self.frame, text=title, font=("Roboto", 14, "bold"), wraplength=550, justify="left")
        self.title_label.pack(side="top", padx=10, pady=(10, 5), anchor="w")

        self.main_progress_label = ctk.CTkLabel(self.frame, text="Download Progress: 0.00%", font=("Roboto", 12))
        self.main_progress_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.size_progress_label = ctk.CTkLabel(self.frame, text="Downloaded: 0.00 MB / 0.00 MB", font=("Roboto", 12))
        self.size_progress_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.time_label = ctk.CTkLabel(self.frame, text="Elapsed Time: 0.00 seconds", font=("Roboto", 12))
        self.time_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.progress_bar = ctk.CTkProgressBar(self.frame, height=10, corner_radius=5)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=10, pady=10, expand=True)

        self.status_label = ctk.CTkLabel(self.frame, text="Starting...", font=("Roboto", 12, "italic"))
        self.status_label.pack(side="top", padx=10, pady=5, anchor="w")

        self.actions_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.actions_frame.pack(fill="x", padx=10, pady=5)

        self.cancel_button = ctk.CTkButton(self.actions_frame, text="Cancel", command=self.cancel, fg_color="#d9534f", hover_color="#c9302c")
        self.cancel_button.pack(side="right")

        self.open_folder_button = ctk.CTkButton(self.actions_frame, text="Open Folder", command=self.open_containing_folder)
        self.play_file_button = ctk.CTkButton(self.actions_frame, text="Play File", command=self.play_file)

    def start_download(self):
        self.start_time = time.time()
        active_downloads[self.task_id] = self
        thread = threading.Thread(target=self._download_thread, daemon=True)
        thread.start Ascending
        thread.start()

    def _progress_hook(self, d):
        if self.cancel_flag:
            raise yt_dlp.utils.DownloadError("Download canceled by the user")
        if d['status'] == 'downloading':
            total_size = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_size = d.get('downloaded_bytes', 0)
            if total_size and downloaded_size:
                progress = downloaded_size / total_size
                downloaded_mb = downloaded_size / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                elapsed_time = time.time() - self.start_time
                speed = (downloaded_size / (1024 * 1024)) / elapsed_time if elapsed_time > 0 else 0
                download_queue.put({
                    'task_id': self.task_id, 'status': 'downloading',
                    'progress': progress, 'downloaded_mb': downloaded_mb,
                    'total_mb': total_mb, 'elapsed_time': elapsed_time,
                    'speed': speed
                })
        elif d['status'] == 'finished':
            elapsed_time = time.time() - self.start_time
            download_queue.put({
                'task_id': self.task_id, 'status': 'finished',
                'filepath': d.get('filename'), 'elapsed_time': elapsed_time
            })

    def _download_thread(self):
        try:
            output_path = os.path.join(self.folder, '%(title)s.%(ext)s')
            ydl_opts = {
                'format': self.quality_format,
                'outtmpl': output_path,
                'progress_hooks': [self._progress_hook],
                'quiet': True,
                'noplaylist': not self.is_playlist,
                'ffmpeg_location': FFMPEG_PATH,
                'postprocessors': [],
                'user_agent': USER_AGENT,
                'socket_timeout': 15,
            }
            if 'audio' in self.quality_format or self.quality_format == 'bestaudio/best':
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',
                })
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
        except yt_dlp.utils.DownloadError as e:
            if "canceled" not in str(e):
                logging.error(f"DownloadError for {self.url}: {e}")
                download_queue.put({'task_id': self.task_id, 'status': 'error', 'message': f"Download failed: {e}"})
        except Exception as e:
            logging.error(f"Unhandled exception for {self.url}: {e}")
            download_queue.put({'task_id': self.task_id, 'status': 'error', 'message': f"An error occurred: {e}"})
        finally:
            if self.task_id in active_downloads:
                download_queue.put({'task_id': self.task_id, 'status': 'done'})

    def update_ui(self, data):
        status = data.get('status')
        if status == 'downloading':
            self.progress_bar.set(data['progress'])
            self.main_progress_label.configure(text=f"Download Progress: {data['progress'] * 100:.2f}%")
            self.size_progress_label.configure(text=f"Downloaded: {data['downloaded_mb']:.2f} MB / {data['total_mb']:.2f} MB")
            self.time_label.configure(text=f"Elapsed Time: {data['elapsed_time']:.2f} seconds, Speed: {data['speed']:.2f} MB/s")
            self.status_label.configure(text="Downloading...")
        elif status == 'finished':
            self.progress_bar.set(1)
            self.main_progress_label.configure(text="Download Progress: 100.00%")
            self.status_label.configure(text=f"Completed in {data['elapsed_time']:.2f} seconds.")
            intermediate_path = data.get('filepath')
            if 'audio' in self.quality_format or self.quality_format == 'bestaudio/best':
                base, _ = os.path.splitext(intermediate_path)
                potential_mp3_path = base + '.mp3'
                self.filepath = potential_mp3_path if os.path.exists(potential_mp3_path) else intermediate_path
            else:
                self.filepath = intermediate_path
            self.cancel_button.pack_forget()
            self.open_folder_button.pack(side="right", padx=(0, 5))
            self.play_file_button.pack(side="right", padx=(0, 5))
        elif status == 'error':
            self.status_label.configure(text=data['message'], text_color="red")
            self.cancel_button.configure(state="disabled")
        elif status == 'cancelled':
            self.status_label.configure(text="Download cancelled.", text_color="orange")
            self.cancel_button.configure(state="disabled")

    def cancel(self):
        self.cancel_flag = True
        self.cancel_button.configure(text="Cancelling...", state="disabled")
        messagebox.showinfo("Cancelling", f"Attempting to cancel download for: {self.title_label.cget('text')}")

    def open_containing_folder(self):
        if self.filepath:
            directory = os.path.dirname(self.filepath)
            try:
                if sys.platform == "win32":
                    os.startfile(directory)
                elif sys.platform == "darwin":
                    subprocess.run(["open", directory], check=True)
                else:
                    subprocess.run(["xdg-open", directory], check=True)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {e}")

    def play_file(self):
        if self.filepath and os.path.exists(self.filepath):
            try:
                if sys.platform == "win32":
                    os.startfile(self.filepath)
                elif sys.platform == "darwin":
                    subprocess.run(["open", self.filepath], check=True)
                else:
                    subprocess.run(["xdg-open", self.filepath], check=True)
            except Exception as e:
                messagebox.showerror("Error", f"Could not play file: {e}")
        else:
            messagebox.showerror("Error", "File not found. It may have been moved or deleted.")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Video Downloader")
        self.geometry("700x800")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.info_dict = None
        self.thumbnail_photo = None

        self._create_widgets()
        self.process_queues()
        if not FFMPEG_PATH:
            messagebox.showwarning("FFmpeg Not Found", f"FFmpeg not found. Downloads requiring format merging or audio conversion may fail.")

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        input_frame = ctk.CTkFrame(self, corner_radius=10)
        input_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(input_frame, text="YouTube URL:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.url_entry = ctk.CTkEntry(input_frame, placeholder_text="Enter YouTube URL")
        self.url_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        paste_button = ctk.CTkButton(input_frame, text="Paste", command=self.paste_from_clipboard, width=80)
        paste_button.grid(row=0, column=2, padx=(0, 10), pady=10)

        self.load_details_button = ctk.CTkButton(input_frame, text="Load Details", command=self.start_load_video_details_thread)
        self.load_details_button.grid(row=0, column=3, padx=10, pady=10)

        self.theme_switch = ctk.CTkSwitch(input_frame, text="Dark Mode", command=self.toggle_theme)
        self.theme_switch.grid(row=0, column=4, padx=10, pady=10)
        self.theme_switch.select()

        details_options_frame = ctk.CTkFrame(self, corner_radius=10)
        details_options_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        details_options_frame.grid_columnconfigure(1, weight=1)

        self.thumbnail_label = ctk.CTkLabel(details_options_frame, text="")
        self.thumbnail_label.grid(row=0, column=0, rowspan=4, padx=10, pady=10)

        self.video_info_label = ctk.CTkLabel(details_options_frame, text="Enter a URL and click 'Load Details'", justify="left", wraplength=400)
        self.video_info_label.grid(row=0, column=1, sticky="w", padx=10, pady=10)

        ctk.CTkLabel(details_options_frame, text="Download Folder:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.folder_path = tk.StringVar(value=DEFAULT_DOWNLOAD_FOLDER)
        self.folder_entry = ctk.CTkEntry(details_options_frame, textvariable=self.folder_path)
        self.folder_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        ctk.CTkButton(details_options_frame, text="Browse", command=self.browse_folder, width=100).grid(row=1, column=2, padx=10, pady=5)

        ctk.CTkLabel(details_options_frame, text="Quality:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.quality_var = tk.StringVar()
        self.quality_combobox = ctk.CTkComboBox(details_options_frame, variable=self.quality_var, state="readonly", values=["Load details first"])
        self.quality_combobox.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(details_options_frame, text="Playlist:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.playlist_var = tk.StringVar(value="Single Video")
        self.playlist_combobox = ctk.CTkComboBox(details_options_frame, variable=self.playlist_var, values=["Single Video", "Entire Playlist"], state="readonly")
        self.playlist_combobox.grid(row=3, column=1, padx=10, pady=5, sticky="ew")

        action_frame = ctk.CTkFrame(self, corner_radius=10)
        action_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        action_frame.grid_columnconfigure(0, weight=1)
        self.download_button = ctk.CTkButton(action_frame, text="Download", command=self.start_new_download, height=40, font=("Roboto", 16, "bold"), state="disabled")
        self.download_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        downloads_container = ctk.CTkScrollableFrame(self, label_text="Downloads")
        downloads_container.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        self.downloads_frame = downloads_container

    def toggle_theme(self):
        if self.theme_switch.get() == 1:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

    def paste_from_clipboard(self):
        try:
            clipboard_content = self.clipboard_get()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, clipboard_content)
        except tk.TclError:
            pass

    def is_valid_youtube_url(self, url):
        youtube_regex = (
            r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/'
            r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        return bool(re.match(youtube_regex, url))

    def start_load_video_details_thread(self):
        url = self.url_entry.get()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        if not self.is_valid_youtube_url(url):
            messagebox.showerror("Error", "Please enter a valid YouTube URL")
            self.video_info_label.configure(text="Invalid URL. Please try again.")
            self.load_details_button.configure(state="normal")
            return

        self.video_info_label.configure(text="Loading video details... Please wait.")
        self.download_button.configure(state="disabled")
        self.load_details_button.configure(text="Loading...", state="disabled")
        self.quality_combobox.configure(values=["Loading..."], state="readonly")
        self.quality_combobox.set("Loading...")
        self.thumbnail_label.configure(image=None)
        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress_bar.grid(row=4, column=0, padx=10, pady=10, sticky="ew")
        self.progress_bar.start()
        self.update_idletasks()

        thread = threading.Thread(target=self._load_video_details_in_thread, args=(url,), daemon=True)
        thread.start()

    def _load_video_details_in_thread(self, url):
        logging.info(f"Thread started for {url}")
        info_dict = None
        thumbnail_img_data = None
        error_message = None
        retries = 3
        retry_delay = 2

        for attempt in range(retries):
            try:
                with timeout(30):
                    ydl_opts = {
                        'quiet': True,
                        'skip_download': True,
                        'user_agent': USER_AGENT,
                        'cachedir': False,
                        'skip_update': True,
                        'nocheckcertificate': True,
                        'socket_timeout': 15,
                    }
                    if self.playlist_var.get() == "Entire Playlist":
                        ydl_opts['extract_flat'] = True
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info_dict = ydl.extract_info(url, download=False)
                thumbnail_url = info_dict.get('thumbnail')
                if thumbnail_url:
                    response = requests.get(thumbnail_url, timeout=10, headers={'User-Agent': USER_AGENT})
                    response.raise_for_status()
                    thumbnail_img_data = BytesIO(response.content)
                break
            except TimeoutError:
                logging.warning(f"Timeout on attempt {attempt + 1} for {url}")
                error_message = "Operation timed out while loading video details."
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                    continue
            except yt_dlp.utils.DownloadError as e:
                error_message = f"Could not load video details: {e}"
                logging.error(f"yt-dlp error loading details for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                    continue
            except Exception as e:
                error_message = f"An unexpected error occurred: {e}"
                logging.error(f"Unhandled exception loading details for {url}: {e}")
                break
        else:
            logging.error(f"All {retries} attempts failed for {url}")

        logging.info(f"Thread completed for {url}")
        details_queue.put({
            'info_dict': info_dict,
            'thumbnail_img_data': thumbnail_img_data,
            'error_message': error_message
        })

    def _update_details_ui(self, data):
        if hasattr(self, 'progress_bar'):
            self.progress_bar.stop()
            self.progress_bar.grid_forget()
        self.load_details_button.configure(text="Load Details", state="normal")
        self.thumbnail_photo = None
        self.info_dict = None

        info_dict = data.get('info_dict')
        thumbnail_img_data = data.get('thumbnail_img_data')
        error_message = data.get('error_message')

        if error_message:
            messagebox.showerror("Error", error_message)
            self.video_info_label.configure(text="Failed to load details.")
            self.quality_combobox.configure(values=["Load details first"], state="readonly")
            self.quality_combobox.set("Load details first")
            self.thumbnail_label.configure(image=None)
            return

        self.info_dict = info_dict
        title = info_dict.get('title', 'Unknown Title')
        duration = info_dict.get('duration', 0)
        uploader = info_dict.get('uploader', 'Unknown Uploader')
        info_text = f"Title: {title}\nDuration: {duration // 60}m {duration % 60}s\nUploader: {uploader}"
        self.video_info_label.configure(text=info_text)

        if thumbnail_img_data:
            try:
                img = Image.open(thumbnail_img_data)
                img.thumbnail((160, 90), Image.Resampling.LANCZOS)
                self.thumbnail_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                self.thumbnail_label.configure(image=self.thumbnail_photo)
            except Exception as e:
                logging.error(f"Failed to display thumbnail: {e}")
                self.thumbnail_label.configure(image=None)
        else:
            self.thumbnail_label.configure(image=None)

        formats = info_dict.get('formats', [])
        quality_options = []
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                resolution = f.get('height', 'Unknown') if f.get('height') else 'Unknown Resolution'
                ext = f.get('ext', 'mp4')
                filesize = f.get('filesize') or f.get('filesize_approx')
                size_mb = f"{filesize / (1024*1024):.2f} MB" if filesize else "Unknown size"
                quality_options.append((f['format_id'], f"Video: {resolution}p ({ext}) - {size_mb}"))
            elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                ext = f.get('ext', 'mp3')
                filesize = f.get('filesize') or f.get('filesize_approx')
                size_mb = f"{filesize / (1024*1024):.2f} MB" if filesize else "Unknown size"
                quality_options.append((f['format_id'], f"Audio: {ext.upper()} - {size_mb}"))
        quality_options.append(('bestaudio/best', "Audio only (mp3) - Best Quality"))

        if quality_options:
            self.quality_combobox.configure(values=[q[1] for q in quality_options], state="readonly")
            self.quality_map = {display: f_id for f_id, display in quality_options}
            self.quality_combobox.set(quality_options[0][1])
            self.download_button.configure(state="normal")
        else:
            self.video_info_label.configure(text="No downloadable formats found for this URL.")
            self.quality_combobox.configure(values=["No formats found"], state="readonly")
            self.quality_combobox.set("No formats found")
            self.download_button.configure(state="disabled")

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path.set(folder_selected)

    def start_new_download(self):
        url = self.url_entry.get()
        folder = self.folder_path.get()
        selected_quality_display = self.quality_combobox.get()

        if not self.info_dict:
            messagebox.showerror("Error", "Please load video details first.")
            return
        if not all([url, folder, selected_quality_display]):
            messagebox.showerror("Error", "Please ensure URL, folder, and quality are set.")
            return
        if not os.path.exists(folder):
            messagebox.showerror("Error", "The selected download folder does not exist.")
            return

        quality_format_id = self.quality_map.get(selected_quality_display)
        if not quality_format_id:
            messagebox.showerror("Error", "Invalid quality selected. Please load details again.")
            return

        is_playlist = self.playlist_var.get() == "Entire Playlist"
        if is_playlist and not messagebox.askyesno("Playlist Download", "You have selected to download an entire playlist. This might take a long time and consume significant data. Continue?"):
            return

        if is_playlist:
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'user_agent': USER_AGENT}) as ydl:
                playlist_info = ydl.extract_info(url, download=False)
                for entry in playlist_info.get('entries', []):
                    DownloadTask(self.downloads_frame, entry['url'], folder, quality_format_id, False, entry)
        else:
            DownloadTask(self.downloads_frame, url, folder, quality_format_id, is_playlist, self.info_dict)

    def process_queues(self):
        try:
            while not download_queue.empty():
                data = download_queue.get_nowait()
                task_id = data.get('task_id')
                task = active_downloads.get(task_id)
                if task:
                    task.update_ui(data)
                    if data['status'] == 'done':
                        if task_id in active_downloads:
                            del active_downloads[task_id]
        except queue.Empty:
            pass

        try:
            while not details_queue.empty():
                data = details_queue.get_nowait()
                self._update_details_ui(data)
                self.update_idletasks()
        except queue.Empty:
            pass

        self.after(50, self.process_queues)

if __name__ == "__main__":
    app = App()
    app.mainloop()