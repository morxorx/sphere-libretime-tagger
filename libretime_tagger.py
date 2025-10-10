#!/usr/bin/env python3
"""
libretime_tagger.py - Refactored MP3 Tagger with improved architecture
"""

import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, NamedTuple, List
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, APIC, error, TPE1, TALB, TRCK, TCOM
from PIL import Image, UnidentifiedImageError, ImageTk
import io

# ----------------- Data Models ----------------- #

class ValidationResult(NamedTuple):
    success: bool
    message: str = ""
    value: any = None

class TaggingResult(NamedTuple):
    success: bool
    message: str = ""
    new_filepath: Optional[Path] = None

class MP3Tags(NamedTuple):
    title: str
    artist: str
    album: str
    track_number: str
    composer: str

# ----------------- Configuration ----------------- #

SOUNDCLOUD_MAX_TITLE = 100
MAX_COVER_SIZE = (1400, 1400)
COVER_PREVIEW_SIZE = 200

# ----------------- Core Business Logic ----------------- #

class MP3TaggerEngine:
    """Handles the core MP3 tagging operations"""
    
    @staticmethod
    def validate_hosts(hosts: str) -> ValidationResult:
        if not hosts.strip():
            return ValidationResult(True, "No hosts provided", "")
        
        # Clean up the format - ensure proper comma separation with space
        cleaned_hosts = re.sub(r'\s*,\s*', ', ', hosts.strip())
        cleaned_hosts = re.sub(r'\s+', ' ', cleaned_hosts)  # Remove extra spaces
        
        if not re.match(r"^[^,]+(, [^,]+)*$", cleaned_hosts):
            return ValidationResult(False, "Hosts must be comma-separated with space after comma (e.g., 'DJ A, DJ B')")
        
        return ValidationResult(True, "", cleaned_hosts)

    @staticmethod
    def validate_episode_number(num: str) -> ValidationResult:
        if not num.strip():
            return ValidationResult(True, "No episode number provided", "")
        if not num.strip().isdigit():
            return ValidationResult(False, "Episode number must be numeric")
        return ValidationResult(True, "", str(int(num.strip())))

    @staticmethod
    def get_broadcast_date(day: str, month: str, year: str) -> ValidationResult:
        day = day.strip()
        month = month.strip()
        year = year.strip()
        
        # Check if any field is empty
        if not day or not month or not year:
            return ValidationResult(False, "Broadcast date is required - please enter day, month, and year")
        
        try:
            dt = datetime(int(year), int(month), int(day))
            return ValidationResult(True, "", dt.strftime("%d.%m.%Y"))
        except ValueError as e:
            return ValidationResult(False, f"Invalid date combination: {e}")

    @staticmethod
    def sanitize_filename(name: str) -> str:
        sanitized = re.sub(r'[\\/:*?"<>|]', "_", name)
        sanitized = sanitized.strip().rstrip(".")
        return sanitized

    @staticmethod
    def build_filename_parts(show: str, episode: str, episode_title: str, hosts: str, date: str) -> List[str]:
        """Build filename parts, skipping empty elements to avoid extra separators"""
        parts = [show]
        
        if episode:
            parts.append(episode)
        
        if episode_title:
            parts.append(episode_title)
        
        if hosts:
            parts.append(hosts)
        
        if date:
            parts.append(date)
            
        return parts

    @staticmethod
    def truncate_episode_title(filename_parts: List[str], episode_title: str) -> Tuple[str, bool]:
        """Truncate episode title if needed to fit SoundCloud limit"""
        full_filename = " - ".join(filename_parts)
        if len(full_filename) <= SOUNDCLOUD_MAX_TITLE:
            return episode_title, False

        # Rebuild without episode title to calculate available space
        parts_without_title = [p for p in filename_parts if p != episode_title]
        base_length = len(" - ".join(parts_without_title)) + 3  # +3 for " - " separators around title
        
        remaining = SOUNDCLOUD_MAX_TITLE - base_length
        if remaining <= 0:
            return "", True
        
        truncated_title = episode_title[:remaining] + "…"
        return truncated_title, True

    @staticmethod
    def process_cover_art(cover_path: str) -> ValidationResult:
        """Convert to JPEG and resize max 1400x1400, return bytes for ID3."""
        try:
            img = Image.open(cover_path)
        except (UnidentifiedImageError, IOError) as e:
            return ValidationResult(False, f"Cannot open image: {e}")
        
        # Check for PNG transparency
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            return ValidationResult(False, "PNG images with transparency are not allowed")
        
        try:
            img = img.convert("RGB")
            img.thumbnail(MAX_COVER_SIZE, Image.LANCZOS)
            img_bytes = io.BytesIO()
            img.save(img_bytes, format="JPEG", quality=85)  # Reduced quality for smaller size
            img_bytes.seek(0)
            return ValidationResult(True, "", img_bytes.read())
        except Exception as e:
            return ValidationResult(False, f"Error processing image: {e}")

    @staticmethod
    def prepare_tags(show: str, episode: str, episode_title: str, hosts: str, date: str) -> MP3Tags:
        """Prepare all tag values for writing"""
        # Build title parts, skipping empty elements
        title_parts = [show]
        if episode:
            title_parts.append(episode)
        if episode_title:
            title_parts.append(episode_title)
        if hosts:
            title_parts.append(hosts)
        if date:
            title_parts.append(date)
            
        title_str = " - ".join(title_parts)

        return MP3Tags(
            title=title_str,
            artist=hosts or "",
            album=show,
            track_number=episode or "",
            composer=date or ""
        )

    @staticmethod
    def generate_filename(show: str, episode: str, episode_title: str, hosts: str, date: str) -> Tuple[str, bool]:
        """Generate safe filename and return truncation status"""
        # Build initial filename parts
        filename_parts = MP3TaggerEngine.build_filename_parts(show, episode, episode_title, hosts, date)
        
        # Check if truncation is needed (only if we have an episode title)
        was_truncated = False
        if episode_title and episode_title in filename_parts:
            truncated_title, was_truncated = MP3TaggerEngine.truncate_episode_title(filename_parts, episode_title)
            if was_truncated:
                # Replace the episode title in the parts list
                title_index = filename_parts.index(episode_title)
                filename_parts[title_index] = truncated_title
        
        filename_str = " - ".join(filename_parts)
        safe_filename = MP3TaggerEngine.sanitize_filename(filename_str)
        
        return f"{safe_filename}.mp3", was_truncated

    @staticmethod
    def validate_operation(mp3_path: Path, new_filename: str) -> ValidationResult:
        """Validate if the tagging operation can proceed"""
        if not mp3_path.exists():
            return ValidationResult(False, "MP3 file does not exist")
        
        if mp3_path.suffix.lower() != ".mp3":
            return ValidationResult(False, "Selected file is not an MP3")
        
        new_path = mp3_path.parent / new_filename
        if new_path.exists() and new_path != mp3_path:
            return ValidationResult(False, f"File with target name already exists: {new_filename}")
        
        return ValidationResult(True)

    @staticmethod
    def write_id3_tags(mp3_path: Path, tags: MP3Tags, cover_data: Optional[bytes] = None) -> ValidationResult:
        """Write ID3 tags to MP3 file"""
        try:
            try:
                id3 = ID3(mp3_path)
            except ID3NoHeaderError:
                id3 = ID3()

            # Update standard frames
            id3["TIT2"] = TIT2(encoding=3, text=tags.title)
            id3["TPE1"] = TPE1(encoding=3, text=tags.artist)
            id3["TALB"] = TALB(encoding=3, text=tags.album)
            id3["TRCK"] = TRCK(encoding=3, text=tags.track_number)
            if tags.composer:
                id3["TCOM"] = TCOM(encoding=3, text=tags.composer)

            # Remove existing cover art to avoid duplicates
            for key in list(id3.keys()):
                if key.startswith('APIC'):
                    del id3[key]
            
            # Embed cover art if provided
            if cover_data:
                id3.add(APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover_data
                ))

            id3.save(mp3_path)
            return ValidationResult(True)
        except error as e:
            return ValidationResult(False, f"Error writing ID3 tags: {e}")

    @staticmethod
    def rename_mp3_file(old_path: Path, new_filename: str) -> ValidationResult:
        """Rename MP3 file with error handling"""
        try:
            new_path = old_path.parent / new_filename
            old_path.rename(new_path)
            return ValidationResult(True, "", new_path)
        except Exception as e:
            return ValidationResult(False, f"Error renaming file: {e}")

    @staticmethod
    def backup_original_file(file_path: Path) -> ValidationResult:
        """Create a backup of the original file"""
        try:
            backup_path = file_path.with_suffix('.mp3.original')
            if backup_path.exists():
                backup_path.unlink()  # Remove existing backup
            import shutil
            shutil.copy2(file_path, backup_path)
            return ValidationResult(True, "", backup_path)
        except Exception as e:
            return ValidationResult(False, f"Could not create backup: {e}")

# ----------------- GUI Application ----------------- #

class MP3TaggerGUI:
    def __init__(self, master):
        self.master = master
        self.engine = MP3TaggerEngine()
        self.cover_image = None
        self.setup_gui()

    def setup_gui(self):
        """Initialize the GUI components"""
        self.master.title("LibreTime MP3 Tagger - Cross Platform")
        self.master.resizable(True, False)
        self.master.columnconfigure(1, weight=1)

        self.create_file_selection()
        self.create_metadata_fields()
        self.create_date_fields()
        self.create_cover_art_section()
        self.create_action_buttons()
        self.create_output_area()

    def create_file_selection(self):
        """Create file selection widgets"""
        tk.Label(self.master, text="Select MP3 file:").grid(
            row=0, column=0, sticky="w", padx=5
        )
        self.file_entry = tk.Entry(self.master)
        self.file_entry.grid(
            row=0, column=1, sticky="ew", padx=5, pady=3
        )
        tk.Button(self.master, text="Browse", command=self.browse_file, width=10).grid(
            row=0, column=2, padx=5
        )

    def create_metadata_fields(self):
        """Create metadata input fields"""
        # Hosts/Contributors
        tk.Label(self.master, text="Hosts/Contributors (comma):").grid(
            row=1, column=0, sticky="w", padx=5
        )
        self.hosts_entry = tk.Entry(self.master)
        self.hosts_entry.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=3
        )

        # Show Name
        tk.Label(self.master, text="Show Name:").grid(
            row=2, column=0, sticky="w", padx=5
        )
        self.show_entry = tk.Entry(self.master)
        self.show_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=3
        )

        # Episode Number & Title
        tk.Label(self.master, text="Episode Number:").grid(
            row=3, column=0, sticky="w", padx=5
        )
        
        # Create a frame for episode fields to ensure proper alignment
        episode_frame = tk.Frame(self.master)
        episode_frame.grid(row=3, column=1, columnspan=2, sticky="ew", padx=5, pady=3)
        episode_frame.columnconfigure(1, weight=1)  # Make episode title expand
        
        self.episode_entry = tk.Entry(episode_frame, width=10)
        self.episode_entry.grid(row=0, column=0, sticky="w", padx=(0, 5))
        
        tk.Label(episode_frame, text="Episode Title:").grid(
            row=0, column=1, sticky="e", padx=(0, 5)
        )
        self.episode_title_entry = tk.Entry(episode_frame)
        self.episode_title_entry.grid(row=0, column=2, sticky="ew")

    def create_date_fields(self):
        """Create date input fields"""
        tk.Label(self.master, text="Broadcast Date:").grid(
            row=4, column=0, sticky="w", padx=5
        )
        date_frame = tk.Frame(self.master)
        date_frame.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=3)
        
        tk.Label(date_frame, text="Day").grid(row=0, column=0, padx=(0, 2))
        self.day_entry = tk.Entry(date_frame, width=4)
        self.day_entry.grid(row=0, column=1, padx=(0, 10))
        
        tk.Label(date_frame, text="Month").grid(row=0, column=2, padx=(0, 2))
        self.month_entry = tk.Entry(date_frame, width=4)
        self.month_entry.grid(row=0, column=3, padx=(0, 10))
        
        tk.Label(date_frame, text="Year").grid(row=0, column=4, padx=(0, 2))
        self.year_entry = tk.Entry(date_frame, width=6)
        self.year_entry.grid(row=0, column=5, padx=(0, 0))

    def create_cover_art_section(self):
        """Create cover art selection and preview"""
        tk.Label(self.master, text="Cover Art:").grid(
            row=5, column=0, sticky="w", padx=5
        )
        self.cover_entry = tk.Entry(self.master)
        self.cover_entry.grid(
            row=5, column=1, sticky="ew", padx=5, pady=3
        )
        tk.Button(self.master, text="Browse", command=self.browse_cover, width=10).grid(
            row=5, column=2, padx=5
        )

        # Cover Preview - use a frame to eliminate the grey border
        cover_frame = tk.Frame(self.master, bg="white", relief="sunken", bd=1)
        cover_frame.grid(row=5, column=3, padx=5, pady=5)
        
        self.cover_canvas = tk.Canvas(
            cover_frame, 
            width=COVER_PREVIEW_SIZE, 
            height=COVER_PREVIEW_SIZE,
            bg="white", 
            highlightthickness=0  # Remove canvas border
        )
        self.cover_canvas.pack()

    def create_action_buttons(self):
        """Create action buttons"""
        button_frame = tk.Frame(self.master)
        button_frame.grid(row=6, column=0, columnspan=4, pady=10)
        
        tk.Button(button_frame, text="Preview", command=self.preview, width=12).pack(
            side="left", padx=5
        )
        tk.Button(button_frame, text="Save", command=self.save, width=12).pack(
            side="left", padx=5
        )
        tk.Button(button_frame, text="Clear", command=self.clear_all, width=12).pack(
            side="left", padx=5
        )

    def create_output_area(self):
        """Create output text area"""
        self.output_box = scrolledtext.ScrolledText(
            self.master, 
            width=80, 
            height=15, 
            state="disabled"
        )
        self.output_box.grid(
            row=7, column=0, columnspan=4, padx=5, pady=5, sticky="ew"
        )

    def browse_file(self):
        """Browse for MP3 file"""
        file_path = filedialog.askopenfilename(filetypes=[("MP3 Files", "*.mp3")])
        if file_path:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, file_path)

    def browse_cover(self):
        """Browse for cover art image"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Image Files", "*.jpg *.jpeg *.png")]
        )
        if file_path:
            self.cover_entry.delete(0, tk.END)
            self.cover_entry.insert(0, file_path)
            self.show_cover_preview(file_path)

    def show_cover_preview(self, cover_path: str):
        """Display cover art preview without grey borders"""
        self.cover_canvas.delete("all")
        try:
            img = Image.open(cover_path)
            img.thumbnail((COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE), Image.LANCZOS)
            
            self.cover_image = ImageTk.PhotoImage(img)
            
            # Calculate position to center the image
            x = (COVER_PREVIEW_SIZE - self.cover_image.width()) // 2
            y = (COVER_PREVIEW_SIZE - self.cover_image.height()) // 2
            
            # Create image on canvas - fill the entire canvas with white first
            self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
            self.cover_canvas.create_image(x, y, anchor="nw", image=self.cover_image)
            
        except Exception as e:
            # Clear canvas and show error message
            self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
            self.cover_canvas.create_text(
                COVER_PREVIEW_SIZE // 2, 
                COVER_PREVIEW_SIZE // 2,
                text="Invalid image", 
                fill="red", 
                anchor="center"
            )
            self.cover_image = None

    def clear_all(self):
        """Clear all input fields and reset the form"""
        # Clear all entry fields
        self.file_entry.delete(0, tk.END)
        self.hosts_entry.delete(0, tk.END)
        self.show_entry.delete(0, tk.END)
        self.episode_entry.delete(0, tk.END)
        self.episode_title_entry.delete(0, tk.END)
        self.day_entry.delete(0, tk.END)
        self.month_entry.delete(0, tk.END)
        self.year_entry.delete(0, tk.END)
        self.cover_entry.delete(0, tk.END)
        
        # Reset field backgrounds to white
        for entry in [self.file_entry, self.hosts_entry, self.show_entry, 
                     self.episode_entry, self.episode_title_entry, 
                     self.day_entry, self.month_entry, self.year_entry, 
                     self.cover_entry]:
            entry.config(bg="white")
        
        # Clear cover preview - fill with white
        self.cover_canvas.delete("all")
        self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
        self.cover_image = None
        
        # Clear output box
        self.output_box.config(state="normal")
        self.output_box.delete(1.0, tk.END)
        self.output_box.config(state="disabled")
        
        # Set focus to first field
        self.file_entry.focus_set()

    def get_input_values(self) -> Dict[str, str]:
        """Get all input values from the form"""
        return {
            "file": self.file_entry.get(),
            "hosts": self.hosts_entry.get(),
            "show": self.show_entry.get(),
            "episode": self.episode_entry.get(),
            "episode_title": self.episode_title_entry.get(),
            "day": self.day_entry.get(),
            "month": self.month_entry.get(),
            "year": self.year_entry.get(),
            "cover": self.cover_entry.get(),
        }

    def set_field_validation_style(self, entry_widget: tk.Entry, value: str, valid: bool = True):
        """Set visual validation style for input fields"""
        if not value.strip():
            entry_widget.config(bg="white")
        elif valid:
            entry_widget.config(bg="#d4fcd4")  # Light green
        else:
            entry_widget.config(bg="misty rose")  # Light red

    def validate_all_inputs(self, values: Dict[str, str], preview_mode: bool = True) -> ValidationResult:
        """Validate all user inputs"""
        # Validate file
        file_path = Path(values["file"])
        if not file_path.exists() or file_path.suffix.lower() != ".mp3":
            self.set_field_validation_style(self.file_entry, values["file"], False)
            return ValidationResult(False, "Please select a valid MP3 file.")
        self.set_field_validation_style(self.file_entry, values["file"])

        # Validate hosts (can be empty)
        hosts_result = self.engine.validate_hosts(values["hosts"])
        if not hosts_result.success:
            self.set_field_validation_style(self.hosts_entry, values["hosts"], False)
            return hosts_result
        self.set_field_validation_style(self.hosts_entry, values["hosts"])

        # Validate show name (MUST be filled)
        show = values["show"].strip()
        if not show:
            self.set_field_validation_style(self.show_entry, show, False)
            return ValidationResult(False, "Show Name cannot be empty.")
        self.set_field_validation_style(self.show_entry, show)

        # Validate episode number (can be empty)
        episode_result = self.engine.validate_episode_number(values["episode"])
        if not episode_result.success:
            self.set_field_validation_style(self.episode_entry, values["episode"], False)
            return episode_result
        # Update the field with the cleaned episode number if it exists
        if episode_result.value:
            self.episode_entry.delete(0, tk.END)
            self.episode_entry.insert(0, episode_result.value)
        self.set_field_validation_style(self.episode_entry, values["episode"])

        # Validate date (MUST be filled)
        date_result = self.engine.get_broadcast_date(
            values["day"], values["month"], values["year"]
        )
        for entry, val in zip(
            [self.day_entry, self.month_entry, self.year_entry],
            [values["day"], values["month"], values["year"]]
        ):
            self.set_field_validation_style(entry, val, date_result.success)
        
        if not date_result.success:
            return ValidationResult(False, f"Broadcast date error: {date_result.message}")

        # Validate cover art (can be empty)
        cover_path = values["cover"]
        if cover_path:
            cover_result = self.engine.process_cover_art(cover_path)
            if not cover_result.success:
                self.set_field_validation_style(self.cover_entry, cover_path, False)
                return cover_result
            self.set_field_validation_style(self.cover_entry, cover_path)
            if preview_mode:
                self.show_cover_preview(cover_path)

        return ValidationResult(True, "", {
            "hosts": hosts_result.value,
            "show": show,
            "episode": episode_result.value,
            "date": date_result.value,
            "episode_title": values["episode_title"].strip(),
            "cover_path": cover_path if cover_path else None,
            "hosts_warning": hosts_result.message if hosts_result.message else "",
            "episode_warning": episode_result.message if episode_result.message else ""
        })

    def ask_for_confirmation(self, field_name: str, message: str) -> bool:
        """Ask user for confirmation when optional fields are empty"""
        return messagebox.askyesno(
            f"Missing {field_name}",
            f"{message}\n\nDo you want to continue?"
        )

    def generate_preview_report(self, mp3_path: Path, tags: MP3Tags, 
                              new_filename: str, was_truncated: bool,
                              cover_provided: bool, hosts_warning: str = "",
                              episode_warning: str = "") -> str:
        """Generate preview report"""
        report = [
            f"Original file: {mp3_path.name}",
            f"New filename:  {new_filename}",
            "Tags to write:",
            f"  Artist (Hosts/Contributors): {tags.artist or '(empty)'}",
            f"  Album (Show name):           {tags.album}",
            f"  TrackNumber (Ep#):           {tags.track_number or '(empty)'}",
            f"  Composer (Date):             {tags.composer}",
            f"  Title (ID3):                 {tags.title}",
        ]
        
        # Add warnings for empty optional fields
        if hosts_warning:
            report.append(f"\n⚠️ {hosts_warning}")
        if episode_warning:
            report.append(f"\n⚠️ {episode_warning}")
        
        if was_truncated:
            report.append("\n⚠️ Episode Title truncated in filename to fit 100-character limit. ID3 title uses full episode title.")
        
        if cover_provided:
            report.append("\n📷 Cover art will be embedded (auto-resized/converted to JPEG)")
        
        return "\n".join(report)

    def generate_save_report(self, success: bool, message: str, 
                           new_filepath: Optional[Path] = None,
                           cover_embedded: bool = False) -> str:
        """Generate save operation report"""
        if success:
            report = [f"✅ {message}"]
            if new_filepath:
                report.append(f"✅ Renamed to: {new_filepath.name}")
            if cover_embedded:
                report.append("✅ Cover art embedded (auto-resized/converted to JPEG)")
            return "\n".join(report)
        else:
            return f"❌ {message}"

    def process_operation(self, preview_mode: bool = True):
        """Process tagging operation (preview or save)"""
        values = self.get_input_values()
        
        # Reset all field styles
        for entry in [self.file_entry, self.hosts_entry, self.show_entry, 
                     self.episode_entry, self.episode_title_entry, 
                     self.day_entry, self.month_entry, self.year_entry, 
                     self.cover_entry]:
            entry.config(bg="white")

        # Validate inputs
        validation_result = self.validate_all_inputs(values, preview_mode)
        if not validation_result.success:
            messagebox.showerror("Error", validation_result.message)
            return

        valid_data = validation_result.value
        mp3_path = Path(values["file"])

        # For save mode, ask for confirmation on empty optional fields
        if not preview_mode:
            # Check for empty hosts
            if valid_data["hosts_warning"]:
                if not self.ask_for_confirmation("Hosts", "No Hosts added."):
                    return
            
            # Check for empty episode number
            if valid_data["episode_warning"]:
                if not self.ask_for_confirmation("Episode Number", "No Episode number added."):
                    return

        # Generate filename and tags
        new_filename, was_truncated = self.engine.generate_filename(
            valid_data["show"], valid_data["episode"] or "", 
            valid_data["episode_title"], valid_data["hosts"] or "", 
            valid_data["date"]
        )
        
        tags = self.engine.prepare_tags(
            valid_data["show"], valid_data["episode"] or "", 
            valid_data["episode_title"], valid_data["hosts"] or "", 
            valid_data["date"]
        )

        if preview_mode:
            # Preview mode - just show what would happen
            report = self.generate_preview_report(
                mp3_path, tags, new_filename, was_truncated, 
                bool(valid_data["cover_path"]),
                valid_data["hosts_warning"],
                valid_data["episode_warning"]
            )
        else:
            # Save mode - perform actual operations
            operation_result = self.engine.validate_operation(mp3_path, new_filename)
            if not operation_result.success:
                report = f"❌ {operation_result.message}"
            else:
                # Create backup before modification
                backup_result = self.engine.backup_original_file(mp3_path)
                if not backup_result.success:
                    messagebox.showwarning("Warning", backup_result.message)
                
                # Process cover art only for save operations
                cover_data = None
                if valid_data["cover_path"]:
                    cover_result = self.engine.process_cover_art(valid_data["cover_path"])
                    if cover_result.success:
                        cover_data = cover_result.value
                    else:
                        report = f"❌ {cover_result.message}"
                        self.display_output(report, was_truncated)
                        return

                # Write tags
                tag_result = self.engine.write_id3_tags(mp3_path, tags, cover_data)
                if not tag_result.success:
                    report = f"❌ {tag_result.message}"
                else:
                    # Rename file
                    rename_result = self.engine.rename_mp3_file(mp3_path, new_filename)
                    if rename_result.success:
                        report = self.generate_save_report(
                            True, "File tagged successfully", 
                            rename_result.value, bool(cover_data)
                        )
                    else:
                        report = self.generate_save_report(False, rename_result.message)

        self.display_output(report, was_truncated)

    def display_output(self, report: str, has_warning: bool = False):
        """Display output in the text box with appropriate styling"""
        self.output_box.config(state="normal")
        self.output_box.delete(1.0, tk.END)
        self.output_box.insert(tk.END, report)
        
        if has_warning:
            self.output_box.tag_add("warning", "1.0", tk.END)
            self.output_box.tag_config("warning", background="yellow")
        
        self.output_box.config(state="disabled")
        self.output_box.see(tk.END)  # Auto-scroll to bottom

    def preview(self):
        """Handle preview button click"""
        self.process_operation(preview_mode=True)

    def save(self):
        """Handle save button click"""
        if not messagebox.askyesno("Confirm", "Are you sure you want to save changes? A backup will be created."):
            return
        self.process_operation(preview_mode=False)

# ----------------- Application Entry Point ----------------- #

def main():
    """Main application entry point"""
    try:
        root = tk.Tk()
        app = MP3TaggerGUI(root)
        
        # Center window on screen
        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
        y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
        root.geometry(f"+{x}+{y}")
        
        root.mainloop()
    except Exception as e:
        messagebox.showerror("Fatal Error", f"Application failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
