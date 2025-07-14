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

# Configure logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG)

# Global flag to track cancel status

cancel_flag = False

# Start time to track elapsed time
start_time = None

# Absolute path to ffmpeg (update this path as needed)
FFMPEG_PATH = os.path.join(os.path.dirname(__file__), 'ffmpeg.exe')

# Function to update the progress bar and percentage for each download
def progress_hook(d):
    global cancel_flag, start_time
    if cancel_flag:
        raise yt_dlp.utils.DownloadError("Download canceled by the user")

    if d['status'] == 'downloading':
        try:
            total_size = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded_size = d.get('downloaded_bytes', 0)
            if total_size and downloaded_size:
                progress = (downloaded_size / total_size) * 100
                downloaded_mb = downloaded_size / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                elapsed_time = time.time() - start_time if start_time else 0

                # Update GUI elements
                progress_var.set(progress)
                progress_label.config(text=f"{progress:.2f}%")
                main_progress_label.config(text=f"Download Progress: {progress:.2f}%")
                size_progress_label.config(text=f"Downloaded: {downloaded_mb:.2f} MB / {total_mb:.2f} MB")
                time_label.config(text=f"Elapsed Time: {elapsed_time:.2f} seconds")

        except Exception as e:
            status_log.insert(tk.END, f"Error updating progress: {e}\n")
            logging.error(f"Error updating progress: {e}")

# Function to download YouTube video or audio
def download_video(url, folder, download_format, playlist_option, progress_var, progress_label, title_label, status_log, main_progress_label, size_progress_label, time_label):
    global cancel_flag, start_time

    if not url:
        messagebox.showerror("Error", "Please enter a YouTube URL")
        return

    if not folder:
        messagebox.showerror("Error", "Please select a download folder")
        return

    # Check if download folder exists
    if not os.path.exists(folder):
        messagebox.showerror("Error", "The selected download folder does not exist.")
        return

    cancel_flag = False
    status_log.insert(tk.END, "Starting download...\n")
    status_log.see(tk.END)
    start_time = time.time()

    try:
        # Set options for yt-dlp based on the selected format
        output_path = os.path.join(folder, '%(title)s.%(ext)s')
        logging.debug(f"Output path for download: {output_path}")

        if download_format == 'Audio':
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_path,
                'progress_hooks': [progress_hook],
                'quiet': True,
                'concurrent_fragment_downloads': 1,
                'ffmpeg_location': FFMPEG_PATH,
            }
        else:  # Video format
            ydl_opts = {
                'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]',
                'outtmpl': output_path,
                'progress_hooks': [progress_hook],
                'quiet': True,
                'concurrent_fragment_downloads': 1,
                'ffmpeg_location': FFMPEG_PATH,
            }

        # Add playlist options
        if playlist_option == 'Single Video':
            ydl_opts.update({'noplaylist': True})
        else:
            ydl_opts.update({'noplaylist': False})

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)

            if playlist_option == 'Entire Playlist':
                if 'entries' in info_dict and len(info_dict['entries']) > 0:
                    titles = [entry.get('title', 'Unknown Title') for entry in info_dict['entries']]
                    titles_str = "\n".join(titles)
                    download_all = messagebox.askyesno("Playlist Found", f"The following videos are in the playlist:\n\n{titles_str}\n\nDo you want to download all?")
                    if not download_all:
                        progress_label.config(text="Download cancelled.")
                        status_log.insert(tk.END, "Download cancelled by user.\n")
                        status_log.see(tk.END)
                        return
                else:
                    messagebox.showerror("Error", "No videos found in the playlist.")
                    status_log.insert(tk.END, "No videos found in the playlist.\n")
                    status_log.see(tk.END)
                    return
            else:
                title = info_dict.get('title', 'Unknown Title')
                title_label.config(text=title)

            # Start downloading
            status_log.insert(tk.END, "Downloading...\n")
            status_log.see(tk.END)
            ydl.download([url])
            progress_label.config(text="Download completed!")
            main_progress_label.config(text="Download Progress: 100.00% (Completed)")
            size_progress_label.config(text="Downloaded: Completed")
            elapsed_time = time.time() - start_time
            time_label.config(text=f"Elapsed Time: {elapsed_time:.2f} seconds (Completed)")
            status_log.insert(tk.END, "Download completed successfully.\n")
            status_log.see(tk.END)
    except yt_dlp.utils.DownloadError as e:
        progress_label.config(text="Download cancelled.")
        main_progress_label.config(text="Download Progress: Cancelled")
        size_progress_label.config(text="Downloaded: Cancelled")
        time_label.config(text="Elapsed Time: Cancelled")
        status_log.insert(tk.END, "Download cancelled.\n")
        status_log.see(tk.END)
        logging.error(f"Download cancelled: {e}")
    except Exception as e:
        progress_label.config(text=f"Error: {e}")
        main_progress_label.config(text=f"Download Progress: Error")
        size_progress_label.config(text="Downloaded: Error")
        time_label.config(text="Elapsed Time: Error")
        status_log.insert(tk.END, f"Error: {e}\n")
        status_log.see(tk.END)
        logging.error(f"Error during download: {e}")

# Function to run the download in a separate thread
def start_download_thread():
    url = url_entry.get()
    folder = folder_path.get()
    download_format = format_var.get()
    playlist_option = playlist_var.get()

    # Create a frame to hold progress bar and label for the new download
    download_frame = tk.Frame(downloads_frame, bg="#f4f4f4")
    download_frame.pack(fill="x", pady=5)

    # Title label for the video being downloaded
    global title_label
    title_label = tk.Label(download_frame, text="Loading title...", font=("Arial", 12, "bold"), bg="#f4f4f4", fg="#333333")
    title_label.pack(side="top", padx=10, pady=5, anchor="w")

    # Progress label for individual download
    global progress_label
    progress_label = tk.Label(download_frame, text="0%", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
    progress_label.pack(side="right", padx=10)

    # Main progress label for real-time download percentage
    global main_progress_label
    main_progress_label = tk.Label(download_frame, text="Download Progress: 0.00%", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
    main_progress_label.pack(side="top", padx=10, pady=5, anchor="w")

    # Size progress label for real-time download in MB
    global size_progress_label
    size_progress_label = tk.Label(download_frame, text="Downloaded: 0.00 MB / 0.00 MB", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
    size_progress_label.pack(side="top", padx=10, pady=5, anchor="w")

    # Time label for download progress
    global time_label
    time_label = tk.Label(download_frame, text="Elapsed Time: 0.00 seconds", font=("Arial", 10), bg="#f4f4f4", fg="#333333")
    time_label.pack(side="top", padx=10, pady=5, anchor="w")

    # Progress bar for individual download
    global progress_var
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(download_frame, variable=progress_var, maximum=100, mode='determinate')
    progress_bar.pack(fill="x", padx=10, expand=True)

    # Status log for individual download
    global status_log
    status_log = tk.Text(download_frame, height=4, wrap='word', font=("Arial", 10), bg="#f4f4f4", fg="#333333")
    status_log.pack(fill="x", padx=10, pady=5, expand=True)

    # Update status log to show loading message
    status_log.insert(tk.END, "Loading video details...\n")
    status_log.see(tk.END)

    # Start a new thread for this download
    download_thread = threading.Thread(
        target=download_video,
        args=(url, folder, download_format, playlist_option, progress_var, progress_label, title_label, status_log, main_progress_label, size_progress_label, time_label),
        daemon=True
    )
    download_thread.start()

# Function to browse folder
def browse_folder():
    folder_selected = filedialog.askdirectory()
    folder_path.set(folder_selected)

# Function to cancel the download
def cancel_download():
    global cancel_flag
    cancel_flag = True
    messagebox.showinfo("Cancelled", "Download has been cancelled.")

# Function to get and display the video thumbnail and additional video information
def load_video_details():
    url = url_entry.get()
    if not url:
        messagebox.showerror("Error", "Please enter a YouTube URL")
        return

    video_info_label.config(text="Loading...", font=("Arial", 12))
    root.update_idletasks()

    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'force_generic_extractor': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            thumbnail_url = info_dict.get('thumbnail')
            video_title = info_dict.get('title', 'Unknown Title')
            video_duration = info_dict.get('duration', 'Unknown Duration')
            uploader = info_dict.get('uploader', 'Unknown Uploader')
            video_size = info_dict.get('filesize_approx', None)

            if thumbnail_url:
                response = requests.get(thumbnail_url, timeout=10)
                response.raise_for_status()
                img_data = BytesIO(response.content)
                thumbnail_image = Image.open(img_data)
                thumbnail_image = thumbnail_image.resize((200, 150), Image.LANCZOS)
                thumbnail_photo = ImageTk.PhotoImage(thumbnail_image)

                global thumbnail_label
                if 'thumbnail_label' not in globals():
                    thumbnail_label = tk.Label(root, image=thumbnail_photo, bg="#f4f4f4")
                    thumbnail_label.pack(pady=5)
                else:
                    thumbnail_label.config(image=thumbnail_photo)
                    thumbnail_label.image = thumbnail_photo

            video_size_mb = f"{video_size / (1024 * 1024):.2f}" if isinstance(video_size, int) else 'Unknown'
            video_info_label.config(text=(
                f"• Title: {video_title}\n"
                f"• Duration: {video_duration // 60} min {video_duration % 60} sec\n"
                f"• Uploader: {uploader}\n"
                f"• Size: {video_size_mb} MB"
            ))

    except requests.exceptions.RequestException as e:
        messagebox.showerror("Error", f"Could not load video details: {e}")
        logging.error(f"Error loading video thumbnail: {e}")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while loading video details: {e}")
        logging.error(f"Error loading video details: {e}")

# Create the main application window
root = tk.Tk()
root.title("YouTube Video Downloader")
root.geometry("600x1000")
root.config(bg="#f4f4f4")
root.resizable(False, False)

# Set the default download folder
folder_path = tk.StringVar(value=os.path.expanduser("~/Downloads"))

# URL label and entry field
url_label = tk.Label(root, text="YouTube URL:", font=("Arial", 12), bg="#f4f4f4", fg="#333333")
url_label.pack(pady=10)
url_entry = tk.Entry(root, width=50)
url_entry.pack(pady=5)

# Button to load video details
video_details_button = tk.Button(root, text="Load Video Details", command=load_video_details, bg="#5bc0de", fg="white", font=("Arial", 10))
video_details_button.pack(pady=5)

# Label to display video information
video_info_label = tk.Label(root, text="", font=("Arial", 12), bg="#f4f4f4", fg="#333333", justify="left")
video_info_label.pack(pady=5)

# Folder selection label and button
folder_label = tk.Label(root, text="Download Folder:", font=("Arial", 12), bg="#f4f4f4", fg="#333333")
folder_label.pack(pady=10)
folder_entry = tk.Entry(root, textvariable=folder_path, width=50)
folder_entry.pack(pady=5)
browse_button = tk.Button(root, text="Browse", command=browse_folder, bg="#d9534f", fg="white", font=("Arial", 10))
browse_button.pack(pady=5)

# Create a frame to hold both the format and playlist options side by side
options_frame = tk.Frame(root, bg="#f4f4f4")
options_frame.pack(pady=10)

# Format selection label and combobox
format_label = tk.Label(options_frame, text="Select Format:", font=("Arial", 12), bg="#f4f4f4", fg="#333333")
format_label.grid(row=0, column=0, padx=5, sticky="w")

# Combobox to select format (Audio or Video)
format_var = tk.StringVar()
format_combobox = ttk.Combobox(options_frame, textvariable=format_var, values=["Audio", "Video"], state="readonly", width=15)
format_combobox.grid(row=0, column=1, padx=5)
format_combobox.set("Video")

# Playlist selection label and combobox
playlist_label = tk.Label(options_frame, text="Download Option:", font=("Arial", 12), bg="#f4f4f4", fg="#333333")
playlist_label.grid(row=0, column=2, padx=5, sticky="w")

# Combobox to select download option (Single Video or Entire Playlist)
playlist_var = tk.StringVar()
playlist_combobox = ttk.Combobox(options_frame, textvariable=playlist_var, values=["Single Video", "Entire Playlist"], state="readonly", width=20)
playlist_combobox.grid(row=0, column=3, padx=5)
playlist_combobox.set("Single Video")

# Download button
download_button = tk.Button(root, text="Download", command=start_download_thread, width=20, height=2, bg="#5bc0de", fg="white", font=("Arial", 10))
download_button.pack(pady=10)

# Cancel button
cancel_button = tk.Button(root, text="Cancel", command=cancel_download, width=20, height=2, bg="#d9534f", fg="white", font=("Arial", 10))
cancel_button.pack(pady=5)

# Downloads frame (scrollable area for multiple downloads)
downloads_frame = tk.Frame(root, bg="#f4f4f4")
downloads_frame.pack(fill="both", expand=True, pady=10)

# Scrollbar for downloads frame
downloads_scrollbar = tk.Scrollbar(downloads_frame, orient="vertical")
downloads_scrollbar.pack(side="right", fill="y")

downloads_canvas = tk.Canvas(downloads_frame, yscrollcommand=downloads_scrollbar.set, bg="#f4f4f4")
downloads_canvas.pack(side="left", fill="both", expand=True)

downloads_scrollbar.config(command=downloads_canvas.yview)

# Create a frame inside the canvas
downloads_inner_frame = tk.Frame(downloads_canvas, bg="#f4f4f4")
downloads_canvas.create_window((0, 0), window=downloads_inner_frame, anchor="nw")

downloads_inner_frame.bind("<Configure>", lambda e: downloads_canvas.config(scrollregion=downloads_canvas.bbox("all")))

# Reference downloads frame globally
downloads_frame = downloads_inner_frame

# Label for developer credit
credit_label = tk.Label(root, text="Developed by: Elias Legese", font=("Arial", 10, "italic"), bg="#f4f4f4", fg="#333333")
credit_label.pack(pady=50)

# Start the GUI event loop
root.mainloop()
