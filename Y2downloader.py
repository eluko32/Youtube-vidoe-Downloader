import tkinter as tk
from tkinter import ttk, filedialog, messagebox
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
        # Running in a bundle
        base_path = sys._MEIPASS
    else:
        # Running as a script
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
active_downloads = {} # Store active download tasks

class DownloadTask:
    """Encapsulates a single download operation and its UI elements."""
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
        """Creates the UI frame for this download task."""
        self.frame = tk.Frame(self.master, bg="#f4f4f4", bd=2, relief="groove")
        self.frame.pack(fill="x", pady=5, padx=5)

        title = self.info_dict.get('title', 'Unknown Title')
        self.title_label = tk.Label(self.frame, text=title, font=("Arial", 12, "bold"), bg="#f4f4f4", fg="#333333", wraplength=500, justify="left")
        self.title_label.pack(side="top", padx=10, pady=5, anchor="w")

        self.main_progress_label = tk.Label(self.frame, text="Download Progress: 0.00%", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
        self.main_progress_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.size_progress_label = tk.Label(self.frame, text="Downloaded: 0.00 MB / 0.00 MB", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
        self.size_progress_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.time_label = tk.Label(self.frame, text="Elapsed Time: 0.00 seconds", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
        self.time_label.pack(side="top", padx=10, pady=2, anchor="w")

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.frame, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress_bar.pack(fill="x", padx=10, pady=5, expand=True)

        self.status_label = tk.Label(self.frame, text="Starting...", font=("Arial", 10, "italic"), bg="#f4f4f4", fg="#555555")
        self.status_label.pack(side="top", padx=10, pady=5, anchor="w")

        self.cancel_button = tk.Button(self.frame, text="Cancel", command=self.cancel, bg="#d9534f", fg="white", font=("Arial", 9))
        self.cancel_button.pack(side="right", padx=10, pady=5)

    def start_download(self):
        """Starts the download in a new thread."""
        self.start_time = time.time()
        active_downloads[self.task_id] = self
        
        thread = threading.Thread(target=self._download_thread, daemon=True)
        thread.start()

    def _progress_hook(self, d):
        """yt-dlp progress hook. Puts updates into the thread-safe queue."""
        if self.cancel_flag:
            raise yt_dlp.utils.DownloadError("Download canceled by the user")

        if d['status'] == 'downloading':
            total_size = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_size = d.get('downloaded_bytes', 0)
            
            if total_size and downloaded_size:
                progress = (downloaded_size / total_size) * 100
                downloaded_mb = downloaded_size / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                elapsed_time = time.time() - self.start_time

                update_data = {
                    'task_id': self.task_id,
                    'status': 'downloading',
                    'progress': progress,
                    'downloaded_mb': downloaded_mb,
                    'total_mb': total_mb,
                    'elapsed_time': elapsed_time
                }
                download_queue.put(update_data)
        
        elif d['status'] == 'finished':
            elapsed_time = time.time() - self.start_time
            download_queue.put({'task_id': self.task_id, 'status': 'finished', 'elapsed_time': elapsed_time})


    def _download_thread(self):
        """The actual download logic that runs in a separate thread."""
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

            # Add audio conversion if format is audio-only
            if 'audio' in self.quality_format or self.quality_format == 'bestaudio/best':
                 ydl_opts['postprocessors'].append({
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
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
            # Signal that the task is complete, regardless of outcome
            download_queue.put({'task_id': self.task_id, 'status': 'done'})


    def update_ui(self, data):
        """Updates the UI elements for this task from the main thread."""
        status = data.get('status')
        if status == 'downloading':
            self.progress_var.set(data['progress'])
            self.main_progress_label.config(text=f"Download Progress: {data['progress']:.2f}%")
            self.size_progress_label.config(text=f"Downloaded: {data['downloaded_mb']:.2f} MB / {data['total_mb']:.2f} MB")
            self.time_label.config(text=f"Elapsed Time: {data['elapsed_time']:.2f} seconds")
            self.status_label.config(text="Downloading...")
        elif status == 'finished':
            self.progress_var.set(100)
            self.main_progress_label.config(text="Download Progress: 100.00%")
            self.status_label.config(text=f"Completed in {data['elapsed_time']:.2f} seconds.")
            self.cancel_button.config(state="disabled")
        elif status == 'error':
            self.status_label.config(text=data['message'], fg="red")
            self.cancel_button.config(state="disabled")
        elif status == 'cancelled':
            self.status_label.config(text="Download cancelled.", fg="orange")
            self.cancel_button.config(state="disabled")


    def cancel(self):
        """Flags the download for cancellation."""
        self.cancel_flag = True
        download_queue.put({'task_id': self.task_id, 'status': 'cancelled'})
        messagebox.showinfo("Cancelled", f"Cancelling download for: {self.title_label.cget('text')}")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("700x800")
        self.root.config(bg="#e0e0e0")
        self.root.resizable(True, True)

        self.info_dict = None
        self.thumbnail_photo = None

        self._create_widgets()
        self.process_queue()
        
        if not os.path.exists(FFMPEG_PATH):
            messagebox.showwarning("FFmpeg Not Found", f"ffmpeg.exe not found at the expected location: {FFMPEG_PATH}. Downloads requiring format merging may fail.")

    def _create_widgets(self):
        # --- Main container frame ---
        main_frame = tk.Frame(self.root, bg="#e0e0e0")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Input Frame ---
        input_frame = tk.LabelFrame(main_frame, text="Input", bg="#f0f0f0", font=("Arial", 12))
        input_frame.pack(fill="x", pady=5)

        tk.Label(input_frame, text="YouTube URL:", font=("Arial", 12), bg="#f0f0f0").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.url_entry = tk.Entry(input_frame, width=60)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        self.load_details_button = tk.Button(input_frame, text="Load Video Details", command=self.load_video_details, bg="#5bc0de", fg="white", font=("Arial", 10))
        self.load_details_button.grid(row=0, column=2, padx=5, pady=5)
        
        input_frame.grid_columnconfigure(1, weight=1)

        # --- Details Frame ---
        details_frame = tk.LabelFrame(main_frame, text="Video Details", bg="#f0f0f0", font=("Arial", 12))
        details_frame.pack(fill="x", pady=5)

        self.thumbnail_label = tk.Label(details_frame, bg="#f0f0f0")
        self.thumbnail_label.grid(row=0, column=0, rowspan=4, padx=10, pady=5)

        self.video_info_label = tk.Label(details_frame, text="Enter a URL and click 'Load Details'", font=("Arial", 11), bg="#f0f0f0", justify="left")
        self.video_info_label.grid(row=0, column=1, sticky="w", padx=10)

        # --- Options Frame ---
        options_frame = tk.LabelFrame(main_frame, text="Download Options", bg="#f0f0f0", font=("Arial", 12))
        options_frame.pack(fill="x", pady=5)

        tk.Label(options_frame, text="Download Folder:", font=("Arial", 12), bg="#f0f0f0").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.folder_path = tk.StringVar(value=DEFAULT_DOWNLOAD_FOLDER)
        self.folder_entry = tk.Entry(options_frame, textvariable=self.folder_path, width=50)
        self.folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(options_frame, text="Browse", command=self.browse_folder, bg="#d9534f", fg="white", font=("Arial", 10)).grid(row=0, column=2, padx=5, pady=5)

        tk.Label(options_frame, text="Quality:", font=("Arial", 12), bg="#f0f0f0").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.quality_var = tk.StringVar()
        self.quality_combobox = ttk.Combobox(options_frame, textvariable=self.quality_var, state="readonly", width=47)
        self.quality_combobox.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        tk.Label(options_frame, text="Playlist:", font=("Arial", 12), bg="#f0f0f0").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.playlist_var = tk.StringVar(value="Single Video")
        self.playlist_combobox = ttk.Combobox(options_frame, textvariable=self.playlist_var, values=["Single Video", "Entire Playlist"], state="readonly", width=47)
        self.playlist_combobox.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        
        options_frame.grid_columnconfigure(1, weight=1)

        # --- Action Buttons ---
        action_frame = tk.Frame(main_frame, bg="#e0e0e0")
        action_frame.pack(fill="x", pady=10)
        self.download_button = tk.Button(action_frame, text="Download", command=self.start_new_download, width=20, height=2, bg="#5cb85c", fg="white", font=("Arial", 12, "bold"), state="disabled")
        self.download_button.pack()

        # --- Downloads Area ---
        downloads_container = tk.LabelFrame(main_frame, text="Downloads", bg="#f0f0f0", font=("Arial", 12))
        downloads_container.pack(fill="both", expand=True, pady=5)

        canvas = tk.Canvas(downloads_container, bg="#f0f0f0", highlightthickness=0)
        scrollbar = tk.Scrollbar(downloads_container, orient="vertical", command=canvas.yview)
        self.downloads_frame = tk.Frame(canvas, bg="#f0f0f0")

        self.downloads_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.downloads_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def load_video_details(self):
        url = self.url_entry.get()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return

        self.video_info_label.config(text="Loading...")
        self.download_button.config(state="disabled")
        self.root.update_idletasks()

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
            self.video_info_label.config(text="Failed to load details.")
            return

        # --- Update Info Label ---
        title = self.info_dict.get('title', 'Unknown Title')
        duration = self.info_dict.get('duration', 0)
        uploader = self.info_dict.get('uploader', 'Unknown Uploader')
        
        info_text = (
            f"• Title: {title}\n"
            f"• Duration: {duration // 60} min {duration % 60} sec\n"
            f"• Uploader: {uploader}"
        )
        self.video_info_label.config(text=info_text)

        # --- Update Thumbnail ---
        thumbnail_url = self.info_dict.get('thumbnail')
        if thumbnail_url:
            try:
                response = requests.get(thumbnail_url, timeout=10)
                response.raise_for_status()
                img_data = BytesIO(response.content)
                img = Image.open(img_data).resize((160, 90), Image.LANCZOS)
                self.thumbnail_photo = ImageTk.PhotoImage(img)
                self.thumbnail_label.config(image=self.thumbnail_photo)
            except Exception as e:
                logging.error(f"Failed to load thumbnail: {e}")
                self.thumbnail_label.config(image=None) # Clear image on failure

        # --- Populate Quality ComboBox ---
        formats = self.info_dict.get('formats', [])
        quality_options = []
        for f in formats:
            resolution = f.get('resolution', 'audio only')
            ext = f.get('ext')
            filesize = f.get('filesize') or f.get('filesize_approx')
            size_mb = f"{filesize / (1024*1024):.2f} MB" if filesize else "Unknown size"
            
            # Filter for common, non-adaptive formats for simplicity
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                 quality_options.append((f['format_id'], f"{resolution} ({ext}) - {size_mb}"))
        
        # Add audio only option
        quality_options.append(('bestaudio/best', "Audio only (mp3) - Best Quality"))

        self.quality_combobox['values'] = [q[1] for q in quality_options]
        self.quality_combobox.bind("<<ComboboxSelected>>", lambda e: self.quality_var.set(self.quality_combobox.get()))
        
        # Store format_id and display text separately
        self.quality_map = {display: f_id for f_id, display in quality_options}
        
        if quality_options:
            self.quality_combobox.set(quality_options[0][1])
            self.quality_var.set(quality_options[0][1])
            self.download_button.config(state="normal")
        else:
            self.video_info_label.config(text="No downloadable formats found.")


    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path.set(folder_selected)

    def start_new_download(self):
        url = self.url_entry.get()
        folder = self.folder_path.get()
        selected_quality_display = self.quality_var.get()
        
        if not all([url, folder, selected_quality_display]):
            messagebox.showerror("Error", "Please ensure URL, folder, and quality are set.")
            return
        if not os.path.exists(folder):
            messagebox.showerror("Error", "The selected download folder does not exist.")
            return
        
        quality_format_id = self.quality_map.get(selected_quality_display)
        is_playlist = self.playlist_var.get() == "Entire Playlist"

        if is_playlist:
            if not messagebox.askyesno("Playlist Download", "You have selected to download an entire playlist. This may take a long time. Continue?"):
                return

        DownloadTask(self.downloads_frame, url, folder, quality_format_id, is_playlist, self.info_dict)

    def process_queue(self):
        """Processes messages from the download queue to update the GUI."""
        try:
            while not download_queue.empty():
                data = download_queue.get_nowait()
                task_id = data.get('task_id')
                task = active_downloads.get(task_id)

                if task:
                    if data['status'] == 'done':
                        # Clean up the task from the active list
                        if task_id in active_downloads:
                            del active_downloads[task_id]
                    else:
                        task.update_ui(data)

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()