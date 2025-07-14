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

# --- Path and Environment Setup ---
def get_ffmpeg_path():
    """ Get the path to ffmpeg.exe, handling PyInstaller bundling. """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'ffmpeg.exe')

FFMPEG_PATH = get_ffmpeg_path()

# Add the ffmpeg directory to the system PATH to prevent yt-dlp warnings
ffmpeg_dir = os.path.dirname(FFMPEG_PATH)
if ffmpeg_dir not in os.environ['PATH']:
    os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']

# Configure logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
DEFAULT_DOWNLOAD_FOLDER = os.path.expanduser("~/Downloads")

# --- Global Variables ---
download_queue = queue.Queue()
active_downloads = {}

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

        self.cancel_button = ctk.CTkButton(self.frame, text="Cancel", command=self.cancel, fg_color="#d9534f", hover_color="#c9302c")
        self.cancel_button.pack(side="right", padx=10, pady=10)

    def start_download(self):
        self.start_time = time.time()
        active_downloads[self.task_id] = self
        thread = threading.Thread(target=self._download_thread, daemon=True)
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
                download_queue.put({
                    'task_id': self.task_id, 'status': 'downloading',
                    'progress': progress, 'downloaded_mb': downloaded_mb,
                    'total_mb': total_mb, 'elapsed_time': elapsed_time
                })
        elif d['status'] == 'finished':
            elapsed_time = time.time() - self.start_time
            download_queue.put({'task_id': self.task_id, 'status': 'finished', 'elapsed_time': elapsed_time})

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
                'cookies_from_browser': ('edge',),
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
            download_queue.put({'task_id': self.task_id, 'status': 'done'})

    def update_ui(self, data):
        status = data.get('status')
        if status == 'downloading':
            self.progress_bar.set(data['progress'])
            self.main_progress_label.configure(text=f"Download Progress: {data['progress'] * 100:.2f}%")
            self.size_progress_label.configure(text=f"Downloaded: {data['downloaded_mb']:.2f} MB / {data['total_mb']:.2f} MB")
            self.time_label.configure(text=f"Elapsed Time: {data['elapsed_time']:.2f} seconds")
            self.status_label.configure(text="Downloading...")
        elif status == 'finished':
            self.progress_bar.set(1)
            self.main_progress_label.configure(text="Download Progress: 100.00%")
            self.status_label.configure(text=f"Completed in {data['elapsed_time']:.2f} seconds.")
            self.cancel_button.configure(state="disabled")
        elif status == 'error':
            self.status_label.configure(text=data['message'], text_color="red")
            self.cancel_button.configure(state="disabled")
        elif status == 'cancelled':
            self.status_label.configure(text="Download cancelled.", text_color="orange")
            self.cancel_button.configure(state="disabled")

    def cancel(self):
        self.cancel_flag = True
        download_queue.put({'task_id': self.task_id, 'status': 'cancelled'})
        messagebox.showinfo("Cancelled", f"Cancelling download for: {self.title_label.cget('text')}")

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
        self.process_queue()
        
        if not os.path.exists(FFMPEG_PATH):
            messagebox.showwarning("FFmpeg Not Found", f"ffmpeg.exe not found at the expected location: {FFMPEG_PATH}. Downloads requiring format merging may fail.")

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # --- Input Frame ---
        input_frame = ctk.CTkFrame(self, corner_radius=10)
        input_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(input_frame, text="YouTube URL:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.url_entry = ctk.CTkEntry(input_frame, placeholder_text="Enter YouTube URL")
        self.url_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        paste_button = ctk.CTkButton(input_frame, text="Paste", command=self.paste_from_clipboard, width=80)
        paste_button.grid(row=0, column=2, padx=(0, 10), pady=10)

        self.load_details_button = ctk.CTkButton(input_frame, text="Load Details", command=self.load_video_details)
        self.load_details_button.grid(row=0, column=3, padx=10, pady=10)

        self.theme_switch = ctk.CTkSwitch(input_frame, text="Dark Mode", command=self.toggle_theme)
        self.theme_switch.grid(row=0, column=4, padx=10, pady=10)
        self.theme_switch.select()

        # --- Details & Options Frame ---
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
        self.quality_combobox = ctk.CTkComboBox(details_options_frame, variable=self.quality_var, state="readonly")
        self.quality_combobox.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(details_options_frame, text="Playlist:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.playlist_var = tk.StringVar(value="Single Video")
        self.playlist_combobox = ctk.CTkComboBox(details_options_frame, variable=self.playlist_var, values=["Single Video", "Entire Playlist"], state="readonly")
        self.playlist_combobox.grid(row=3, column=1, padx=10, pady=5, sticky="ew")

        # --- Action Buttons ---
        action_frame = ctk.CTkFrame(self, corner_radius=10)
        action_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        action_frame.grid_columnconfigure(0, weight=1)
        self.download_button = ctk.CTkButton(action_frame, text="Download", command=self.start_new_download, height=40, font=("Roboto", 16, "bold"), state="disabled")
        self.download_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # --- Downloads Area ---
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
            # This can happen if the clipboard is empty
            pass

    def load_video_details(self):
        url = self.url_entry.get()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return

        self.video_info_label.configure(text="Loading...")
        self.download_button.configure(state="disabled")
        self.update_idletasks()

        try:
            ydl_opts = {
                'quiet': True, 
                'skip_download': True,
                'cookies_from_browser': ('edge',)
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.info_dict = ydl.extract_info(url, download=False)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load video details: {e}")
            self.video_info_label.configure(text="Failed to load details.")
            return

        title = self.info_dict.get('title', 'Unknown Title')
        duration = self.info_dict.get('duration', 0)
        uploader = self.info_dict.get('uploader', 'Unknown Uploader')
        info_text = f"Title: {title}\nDuration: {duration // 60}m {duration % 60}s\nUploader: {uploader}"
        self.video_info_label.configure(text=info_text)

        thumbnail_url = self.info_dict.get('thumbnail')
        if thumbnail_url:
            try:
                response = requests.get(thumbnail_url, timeout=10)
                response.raise_for_status()
                img_data = BytesIO(response.content)
                img = Image.open(img_data)
                self.thumbnail_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 90))
                self.thumbnail_label.configure(image=self.thumbnail_photo)
            except Exception as e:
                logging.error(f"Failed to load thumbnail: {e}")
                self.thumbnail_label.configure(image=None)

        formats = self.info_dict.get('formats', [])
        quality_options = []
        for f in formats:
            resolution = f.get('resolution', 'audio only')
            ext = f.get('ext')
            filesize = f.get('filesize') or f.get('filesize_approx')
            size_mb = f"{filesize / (1024*1024):.2f} MB" if filesize else "Unknown size"
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                 quality_options.append((f['format_id'], f"{resolution} ({ext}) - {size_mb}"))
        quality_options.append(('bestaudio/best', "Audio only (mp3) - Best Quality"))

        self.quality_combobox.configure(values=[q[1] for q in quality_options])
        self.quality_map = {display: f_id for f_id, display in quality_options}
        if quality_options:
            self.quality_combobox.set(quality_options[0][1])
            self.download_button.configure(state="normal")
        else:
            self.video_info_label.configure(text="No downloadable formats found.")

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path.set(folder_selected)

    def start_new_download(self):
        url = self.url_entry.get()
        folder = self.folder_path.get()
        selected_quality_display = self.quality_combobox.get()
        if not all([url, folder, selected_quality_display]):
            messagebox.showerror("Error", "Please ensure URL, folder, and quality are set.")
            return
        if not os.path.exists(folder):
            messagebox.showerror("Error", "The selected download folder does not exist.")
            return
        
        quality_format_id = self.quality_map.get(selected_quality_display)
        is_playlist = self.playlist_var.get() == "Entire Playlist"
        if is_playlist and not messagebox.askyesno("Playlist Download", "You have selected to download an entire playlist. Continue?"):
            return

        DownloadTask(self.downloads_frame, url, folder, quality_format_id, is_playlist, self.info_dict)

    def process_queue(self):
        try:
            while not download_queue.empty():
                data = download_queue.get_nowait()
                task_id = data.get('task_id')
                task = active_downloads.get(task_id)
                if task:
                    if data['status'] == 'done':
                        if task_id in active_downloads:
                            del active_downloads[task_id]
                    else:
                        task.update_ui(data)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

if __name__ == "__main__":
    app = App()
    app.mainloop()
