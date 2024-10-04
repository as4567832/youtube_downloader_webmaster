from flask import Flask, request, jsonify, render_template, send_file
from threading import Thread, Lock
import os
import yt_dlp   

app = Flask(__name__)

# Dictionary to store download progress and file paths
downloads = {}
total_videos = 0
current_video_index = 0
index_lock = Lock()

def extract_and_save_urls(playlist_url, output_file):
    """Extracts video URLs from a YouTube playlist using yt_dlp."""
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': 'in_playlist',
            'playlistend': None,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(playlist_url, download=False)
            if 'entries' not in info_dict:
                raise Exception("No entries found in playlist.")

            video_urls = [entry['url'] for entry in info_dict['entries'] if entry]

        with open(output_file, 'w') as file:
            for url in video_urls:
                # Ensure full YouTube URL
                if not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={url}"
                file.write(url + '\n')

        print(f"URLs saved to {output_file}")
        return video_urls
    except Exception as e:
        print(f"Error extracting URLs: {e}")
        return []

def list_available_formats(url):
    """Lists available formats for a given YouTube video URL."""
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'listformats': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            formats = info_dict.get('formats', [])
            format_list = []
            for fmt in formats:
                format_id = fmt.get('format_id')
                format_note = fmt.get('format_note') or ''
                ext = fmt.get('ext')
                resolution = fmt.get('resolution') or f"{fmt.get('height', 'N/A')}p"
                vcodec = fmt.get('vcodec')
                acodec = fmt.get('acodec')
                format_desc = f"{format_id} - {ext} - {resolution} - Vcodec: {vcodec} - Acodec: {acodec} {format_note}"
                format_list.append({
                    'format_id': format_id,
                    'description': format_desc
                })
            return format_list
    except Exception as e:
        print(f"Error listing formats for {url}: {e}")
        return []

def download_video(url, folder_path, download_id, video_urls, selected_format):
    """Downloads a YouTube video using the selected format and updates the downloads dictionary with progress and status."""
    global current_video_index
    downloads[download_id] = {
        'progress': 0,
        'speed': 0,
        'title': '',
        'file_path': '',
        'status': 'Queued',
        'error': None
    }

    def progress_hook(d):
        """Update progress dictionary during download."""
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes:
                percent = (d.get('downloaded_bytes', 0) / total_bytes) * 100
                downloads[download_id]['progress'] = round(percent, 2)
                downloads[download_id]['speed'] = d.get('speed', 0)
                downloads[download_id]['title'] = os.path.basename(d.get('filename', ''))
                downloads[download_id]['status'] = 'Downloading'
        elif d['status'] == 'finished':
            downloads[download_id]['progress'] = 100
            downloads[download_id]['speed'] = 0
            downloads[download_id]['file_path'] = d.get('filename', '')
            downloads[download_id]['status'] = 'Completed'

    # yt_dlp options to download the selected format
    ydl_opts = {
        'outtmpl': os.path.join(folder_path, '%(title)s.%(ext)s'),
        'format': selected_format,  # Use the user-selected format
        'progress_hooks': [progress_hook],
        'quiet': True,
        'noprogress': True,
        'ignoreerrors': True,  # Continue on download errors
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # After successful download, proceed to the next video
        with index_lock:
            current_video_index += 1
        download_next_video(video_urls, folder_path, selected_format)
    except yt_dlp.utils.ExtractorError as e:
        downloads[download_id]['status'] = 'Error'
        downloads[download_id]['error'] = str(e)
        print(f"ExtractorError downloading video {url}: {e}")
        with index_lock:
            current_video_index += 1
        download_next_video(video_urls, folder_path, selected_format)
    except yt_dlp.utils.DownloadError as e:
        downloads[download_id]['status'] = 'Error'
        downloads[download_id]['error'] = str(e)
        print(f"DownloadError downloading video {url}: {e}")
        with index_lock:
            current_video_index += 1
        download_next_video(video_urls, folder_path, selected_format)
    except Exception as e:
        downloads[download_id]['status'] = 'Error'
        downloads[download_id]['error'] = str(e)
        print(f"Unexpected error downloading video {url}: {e}")
        with index_lock:
            current_video_index += 1
        download_next_video(video_urls, folder_path, selected_format)

def download_next_video(video_urls, folder_path, selected_format):
    """Downloads the next video in the list if available."""
    global current_video_index
    with index_lock:
        if current_video_index < len(video_urls):
            video_url = video_urls[current_video_index].strip()
            download_id = f'download_{current_video_index + 1}'
            thread = Thread(target=download_video, args=(video_url, folder_path, download_id, video_urls, selected_format))
            thread.start()
        else:
            print("All downloads complete!")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    """Fetch available formats for the first video in the playlist."""
    playlist_url = request.form.get('playlist_url')
    if not playlist_url:
        return jsonify({'status': 'error', 'message': 'No playlist URL provided.'}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': 'in_playlist',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(playlist_url, download=False)
            if 'entries' not in info_dict or not info_dict['entries']:
                raise Exception("No entries found in playlist.")

            first_entry = info_dict['entries'][0]
            first_video_url = first_entry.get('url')
            if not first_video_url:
                raise Exception("First video URL not found.")

        formats = list_available_formats(first_video_url)
        if not formats:
            return jsonify({'status': 'error', 'message': 'No formats available for the first video.'}), 500

        return jsonify({'status': 'success', 'formats': formats})
    except Exception as e:
        print(f"Error fetching formats: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/start_download', methods=['POST'])
def start_download():
    global total_videos, current_video_index
    data = request.get_json()
    playlist_url = data.get('playlist_url')
    selected_format = data.get('selected_format')

    if not playlist_url or not selected_format:
        return jsonify({'status': 'error', 'message': 'Playlist URL and format selection are required.'}), 400

    output_file = 'extracted_urls.txt'

    # Extract video URLs
    video_urls = extract_and_save_urls(playlist_url, output_file)

    if not video_urls:
        return jsonify({'status': 'error', 'message': 'Failed to extract video URLs.'}), 500

    folder_path = 'download'
    os.makedirs(folder_path, exist_ok=True)

    total_videos = len(video_urls)
    with index_lock:
        current_video_index = 0

    # Start downloading the first video in a new thread
    download_next_video(video_urls, folder_path, selected_format)

    return jsonify({'status': 'Download started', 'total_videos': total_videos})

@app.route('/progress', methods=['GET'])
def progress():
    """Calculates the total download progress."""
    total_progress = 0
    current_title = ""
    current_speed = 0
    active_downloads = 0

    for download_id, data in downloads.items():
        total_progress += data.get('progress', 0)
        if data.get('status') == 'Downloading':
            current_title = data.get('title', '')
            current_speed = data.get('speed', 0)
            active_downloads += 1

    average_progress = total_progress / max(len(downloads), 1)

    return jsonify({
        'total_progress': average_progress,
        'current_title': current_title,
        'current_speed': current_speed,
        'active_downloads': active_downloads
    })

@app.route('/download/<filename>', methods=['GET'])
def download(filename):
    """Provides the downloaded video file for download."""
    return send_file(os.path.join('download', filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
