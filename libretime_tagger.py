#!/usr/bin/env python3
"""
libretime_tagger.py - Refactored MP3 Tagger with improved architecture
"""

import re
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple, NamedTuple, List
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, APIC, error, TPE1, TALB, TRCK, TCOM
from PIL import Image, UnidentifiedImageError, ImageTk
import io
import platform
import subprocess
import calendar

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

# ----------------- Template Management ----------------- #

class TemplateManager:
    """
    Manages template storage and retrieval using JSON files
    """
    
    def __init__(self, app_name: str = "LibreTimeTagger"):
        self.app_name = app_name
        self.config_dir = self._get_config_dir()
        self.template_path = self.config_dir / "template.json"
        self._ensure_config_dir()
    
    def _get_config_dir(self) -> Path:
        """Get platform-appropriate config directory"""
        if platform.system() == "Windows":
            base_dir = Path(os.environ.get('APPDATA', Path.home()))
        elif platform.system() == "Darwin":  # macOS
            base_dir = Path.home() / "Library" / "Application Support"
        else:  # Linux and other Unix-like
            base_dir = Path.home() / ".config"
        
        return base_dir / self.app_name
    
    def _ensure_config_dir(self):
        """Create config directory if it doesn't exist"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def load_template(self) -> Dict[str, str]:
        """
        Load template data from JSON file
        
        Returns:
            Dictionary with template data or empty dict if no template exists
        """
        try:
            if self.template_path.exists():
                with open(self.template_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                    # Validate that we have a dictionary
                    if isinstance(template_data, dict):
                        return template_data
                    else:
                        print(f"Warning: Template file exists but contains invalid data: {self.template_path}")
                        return {}
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"Error loading template from {self.template_path}: {e}")
            return {}
        except Exception as e:
            print(f"Unexpected error loading template: {e}")
            return {}
    
    def save_template(self, 
                     show_name: str = "", 
                     contributors: str = "", 
                     cover_art_path: str = "",
                     auto_load: bool = True) -> bool:
        """
        Save current fields as template
        
        Args:
            show_name: The show name to save
            contributors: The contributors list to save
            cover_art_path: Path to the cover art image
            auto_load: Whether to auto-load this template on startup
            
        Returns:
            True if successful, False otherwise
        """
        try:
            template_data = {
                "show_name": show_name.strip(),
                "contributors": contributors.strip(),
                "cover_art_path": cover_art_path.strip(),
                "auto_load": bool(auto_load),
                "last_updated": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            with open(self.template_path, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            
            print(f"Template saved successfully to: {self.template_path}")
            return True
            
        except Exception as e:
            print(f"Error saving template to {self.template_path}: {e}")
            return False
    
    def update_template_partial(self, **updates) -> bool:
        """
        Update specific fields in the template without overwriting others
        
        Args:
            **updates: Key-value pairs to update in the template
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load existing template
            current_template = self.load_template()
            
            # Update with new values
            current_template.update(updates)
            current_template["last_updated"] = datetime.now().isoformat()
            
            # Save updated template
            with open(self.template_path, 'w', encoding='utf-8') as f:
                json.dump(current_template, f, indent=2, ensure_ascii=False)
            
            return True
            
        except Exception as e:
            print(f"Error updating template: {e}")
            return False
    
    def delete_template(self) -> bool:
        """
        Delete the template file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.template_path.exists():
                self.template_path.unlink()
                print("Template deleted successfully")
                return True
            return True  # No template to delete is also success
        except Exception as e:
            print(f"Error deleting template: {e}")
            return False
    
    def template_exists(self) -> bool:
        """Check if a template file exists"""
        return self.template_path.exists()
    
    def get_template_info(self) -> Dict[str, any]:
        """
        Get template metadata without loading full content
        
        Returns:
            Dictionary with template information
        """
        if not self.template_exists():
            return {"exists": False}
        
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            
            info = {
                "exists": True,
                "file_size": self.template_path.stat().st_size,
                "last_modified": datetime.fromtimestamp(self.template_path.stat().st_mtime),
                "auto_load": template_data.get("auto_load", False),
                "has_show_name": bool(template_data.get("show_name")),
                "has_contributors": bool(template_data.get("contributors")),
                "has_cover_art": bool(template_data.get("cover_art_path")),
            }
            
            if "last_updated" in template_data:
                try:
                    info["last_updated"] = datetime.fromisoformat(template_data["last_updated"])
                except ValueError:
                    info["last_updated"] = "Unknown"
            
            return info
            
        except Exception as e:
            return {"exists": True, "error": str(e)}
    
    def validate_template(self) -> ValidationResult:
        """
        Validate the template file structure and content
        
        Returns:
            ValidationResult with success status and message
        """
        if not self.template_exists():
            return ValidationResult(False, "No template file exists")
        
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            
            # Check required structure
            if not isinstance(template_data, dict):
                return ValidationResult(False, "Template is not a valid JSON object")
            
            # Check for expected fields (these can be empty)
            expected_fields = ["show_name", "contributors", "cover_art_path", "auto_load"]
            for field in expected_fields:
                if field not in template_data:
                    return ValidationResult(False, f"Missing expected field: {field}")
            
            # Validate cover art path if provided
            cover_path = template_data.get("cover_art_path", "")
            if cover_path and not Path(cover_path).exists():
                return ValidationResult(True, f"Warning: Cover art path does not exist: {cover_path}", template_data)
            
            return ValidationResult(True, "Template is valid", template_data)
            
        except json.JSONDecodeError as e:
            return ValidationResult(False, f"Template file contains invalid JSON: {e}")
        except Exception as e:
            return ValidationResult(False, f"Error validating template: {e}")
    
    def export_template(self, export_path: Path) -> bool:
        """
        Export template to a specified location
        
        Args:
            export_path: Path where to export the template
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.template_exists():
                return False
            
            # Copy the template file
            import shutil
            shutil.copy2(self.template_path, export_path)
            print(f"Template exported to: {export_path}")
            return True
            
        except Exception as e:
            print(f"Error exporting template: {e}")
            return False
    
    def import_template(self, import_path: Path) -> bool:
        """
        Import template from a specified location
        
        Args:
            import_path: Path to the template file to import
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate the import file first
            with open(import_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            
            if not isinstance(template_data, dict):
                return False
            
            # Copy the file
            import shutil
            shutil.copy2(import_path, self.template_path)
            print(f"Template imported from: {import_path}")
            return True
            
        except Exception as e:
            print(f"Error importing template: {e}")
            return False

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
    def get_broadcast_date(date_str: str) -> ValidationResult:
        if not date_str.strip():
            return ValidationResult(False, "Broadcast date is required")
        
        try:
            dt = datetime.strptime(date_str.strip(), "%d.%m.%Y")
            return ValidationResult(True, "", dt.strftime("%d.%m.%Y"))
        except ValueError as e:
            return ValidationResult(False, f"Invalid date format. Use DD.MM.YYYY: {e}")

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

# ----------------- Template Testing Functions ----------------- #

def test_template_system():
    """Test function to demonstrate the template system"""
    print("=== Testing Template System ===\n")
    
    # Create template manager
    tm = TemplateManager()
    
    print(f"Config directory: {tm.config_dir}")
    print(f"Template path: {tm.template_path}")
    print(f"Template exists: {tm.template_exists()}\n")
    
    # Test saving a template
    print("1. Saving template...")
    success = tm.save_template(
        show_name="My Awesome Podcast",
        contributors="DJ Alice, DJ Bob",
        cover_art_path="/home/user/podcast_cover.jpg",
        auto_load=True
    )
    print(f"Save successful: {success}\n")
    
    # Test loading template
    print("2. Loading template...")
    template = tm.load_template()
    print(f"Loaded template: {template}\n")
    
    # Test template info
    print("3. Template info...")
    info = tm.get_template_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
    print()
    
    # Test validation
    print("4. Validating template...")
    validation = tm.validate_template()
    print(f"Validation: {validation.success}")
    print(f"Message: {validation.message}\n")
    
    # Test partial update
    print("5. Partial update...")
    tm.update_template_partial(contributors="DJ Alice, DJ Bob, DJ Charlie")
    updated_template = tm.load_template()
    print(f"Updated contributors: {updated_template.get('contributors')}\n")
    
    # Test cleanup
    print("6. Cleaning up...")
    delete_success = tm.delete_template()
    print(f"Delete successful: {delete_success}")

# ----------------- GUI Application ----------------- #

class CalendarDialog:
    """Simple calendar dialog for date selection"""
    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title("Select Date")
        self.top.transient(parent)
        self.top.grab_set()
        
        self.result = None
        
        # Center the dialog
        self.top.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        
        self.create_widgets()
        
    def create_widgets(self):
        today = datetime.today()
        self.year = today.year
        self.month = today.month
        
        # Month and year navigation
        nav_frame = tk.Frame(self.top)
        nav_frame.pack(padx=10, pady=5)
        
        tk.Button(nav_frame, text="<", command=self.prev_month).pack(side=tk.LEFT)
        self.month_label = tk.Label(nav_frame, text="", width=20)
        self.month_label.pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text=">", command=self.next_month).pack(side=tk.LEFT)
        
        # Calendar
        self.cal_frame = tk.Frame(self.top)
        self.cal_frame.pack(padx=10, pady=5)
        
        # Buttons
        btn_frame = tk.Frame(self.top)
        btn_frame.pack(padx=10, pady=10)
        
        tk.Button(btn_frame, text="OK", command=self.ok).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self.cancel).pack(side=tk.LEFT, padx=5)
        
        self.update_calendar()
        
    def update_calendar(self):
        # Update month label
        self.month_label.config(text=calendar.month_name[self.month] + " " + str(self.year))
        
        # Clear existing calendar
        for widget in self.cal_frame.winfo_children():
            widget.destroy()
            
        # Create day headers
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for i, day in enumerate(days):
            tk.Label(self.cal_frame, text=day, width=4).grid(row=0, column=i)
            
        # Get calendar matrix
        cal = calendar.monthcalendar(self.year, self.month)
        
        # Create day buttons
        for week_num, week in enumerate(cal):
            for day_num, day in enumerate(week):
                if day != 0:
                    btn = tk.Button(
                        self.cal_frame, 
                        text=str(day), 
                        width=4,
                        command=lambda d=day: self.select_date(d)
                    )
                    btn.grid(row=week_num + 1, column=day_num, padx=1, pady=1)
                    
    def prev_month(self):
        self.month -= 1
        if self.month < 1:
            self.month = 12
            self.year -= 1
        self.update_calendar()
        
    def next_month(self):
        self.month += 1
        if self.month > 12:
            self.month = 1
            self.year += 1
        self.update_calendar()
        
    def select_date(self, day):
        self.result = f"{day:02d}.{self.month:02d}.{self.year}"
        self.top.destroy()
        
    def ok(self):
        if not self.result:
            # If no date selected, use today
            today = datetime.today()
            self.result = f"{today.day:02d}.{today.month:02d}.{today.year}"
        self.top.destroy()
        
    def cancel(self):
        self.top.destroy()


class MP3TaggerGUI:
    def __init__(self, master):
        self.master = master
        self.engine = MP3TaggerEngine()
        self.template_manager = TemplateManager()
        self.cover_image = None
        
        # Initialize autoload state
        self.autoload_enabled = False
        self.autoload_template_path = None
        
        self.setup_gui()
        
        # Load autoload preference and auto-load template if enabled
        if self.load_autoload_preference():
            self.auto_load_template()

    def setup_gui(self):
        """Initialize the GUI components"""
        self.master.title("LibreTime MP3 Tagger")
        self.master.resizable(False, False)
        
        # Create main frame with vertical layout
        main_frame = tk.Frame(self.master, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid weights for proper resizing
        main_frame.columnconfigure(1, weight=1)
        
        row = 0
        
        # File selection button
        tk.Button(main_frame, text="Select MP3 File", command=self.browse_file, width=20).grid(
            row=row, column=0, columnspan=2, pady=5, sticky="ew"
        )
        row += 1
        
        # Contributors field
        tk.Label(main_frame, text="Contributors (comma-separated):").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.hosts_entry = tk.Entry(main_frame)
        self.hosts_entry.grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1
        
        # Show Name field
        tk.Label(main_frame, text="Show Name:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.show_entry = tk.Entry(main_frame)
        self.show_entry.grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1
        
        # Episode Number field
        tk.Label(main_frame, text="Episode Number:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.episode_entry = tk.Entry(main_frame)
        self.episode_entry.grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1
        
        # Episode Title field
        tk.Label(main_frame, text="Episode Title (optional):").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.episode_title_entry = tk.Entry(main_frame)
        self.episode_title_entry.grid(
            row=row, column=1, sticky="ew", pady=2, padx=(5, 0)
        )
        row += 1
        
        # Broadcast Date with calendar button
        tk.Label(main_frame, text="Broadcast Date:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        date_frame = tk.Frame(main_frame)
        date_frame.grid(row=row, column=1, sticky="ew", pady=2, padx=(5, 0))
        date_frame.columnconfigure(0, weight=1)
        
        self.date_entry = tk.Entry(date_frame)
        self.date_entry.grid(row=0, column=0, sticky="ew")
        
        tk.Button(date_frame, text="📅", command=self.open_calendar, width=3).grid(
            row=0, column=1, padx=(5, 0)
        )
        row += 1
        
        # Cover Art preview (clickable)
        tk.Label(main_frame, text="Cover Art:").grid(
            row=row, column=0, sticky="w", pady=2
        )
        self.cover_canvas = tk.Canvas(
            main_frame, 
            width=COVER_PREVIEW_SIZE, 
            height=COVER_PREVIEW_SIZE,
            bg="white", 
            relief="sunken",
            bd=1,
            cursor="hand2"  # Show hand cursor to indicate clickability
        )
        self.cover_canvas.grid(row=row, column=1, pady=5, padx=(5, 0), sticky="w")
        self.cover_canvas.bind("<Button-1>", self.browse_cover)  # Make canvas clickable
        row += 1
        
        # Action buttons
        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=10)
        
        tk.Button(button_frame, text="Preview", command=self.preview, width=12).pack(
            side="left", padx=5
        )
        tk.Button(button_frame, text="Save", command=self.save, width=12).pack(
            side="left", padx=5
        )
        tk.Button(button_frame, text="Clear", command=self.clear_all, width=12).pack(
            side="left", padx=5
        )
        row += 1
        
        # Output area
        self.output_box = scrolledtext.ScrolledText(
            main_frame, 
            width=60, 
            height=12, 
            state="disabled"
        )
        self.output_box.grid(
            row=row, column=0, columnspan=2, pady=5, sticky="ew"
        )
        row += 1

        # === NEW: Template Management Buttons ===
        template_frame = tk.Frame(main_frame)
        template_frame.grid(row=row, column=0, columnspan=2, pady=10, sticky="ew")
        
        # Configure equal spacing for buttons
        template_frame.columnconfigure(0, weight=1)
        template_frame.columnconfigure(1, weight=1)
        template_frame.columnconfigure(2, weight=1)
        
        # Save Template As button
        self.save_template_btn = tk.Button(
            template_frame, 
            text="Save template as…", 
            command=self.save_template_as,
            width=15
        )
        self.save_template_btn.grid(row=0, column=0, padx=5)
        
        # Load Template button
        self.load_template_btn = tk.Button(
            template_frame, 
            text="Load template", 
            command=self.load_template,
            width=15
        )
        self.load_template_btn.grid(row=0, column=1, padx=5)
        
        # Autoload toggle button
        self.autoload_btn = tk.Button(
            template_frame, 
            text="Autoload", 
            command=self.toggle_autoload,
            width=15
        )
        self.autoload_btn.grid(row=0, column=2, padx=5)
        
        # Track autoload state and template
        self.autoload_enabled = False
        self.autoload_template_path = None
        self.update_autoload_button_style()

    # === NEW: Template Management Methods ===

    def save_template_as(self):
        """Save current fields as a named template file"""
        # Get current field values
        hosts = self.hosts_entry.get().strip()
        show = self.show_entry.get().strip()
        cover_path = getattr(self, 'current_cover_path', '')
        
        if not show:
            messagebox.showwarning("Warning", "Please enter a Show Name before saving as template.")
            return
        
        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            title="Save Template As...",
            defaultextension=".json",
            filetypes=[("JSON Template Files", "*.json"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                # Create template data
                template_data = {
                    "show_name": show,
                    "contributors": hosts,
                    "cover_art_path": cover_path,
                    "auto_load": False,  # Don't auto-load custom templates by default
                    "last_updated": datetime.now().isoformat(),
                    "version": "1.0",
                    "is_custom_template": True  # Mark as custom template
                }
                
                # Save to selected location
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(template_data, f, indent=2, ensure_ascii=False)
                
                self.display_output(f"✅ Template saved as: {os.path.basename(file_path)}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save template: {e}")

    def load_template(self):
        """Load a template file and populate fields"""
        file_path = filedialog.askopenfilename(
            title="Load Template",
            filetypes=[("JSON Template Files", "*.json"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                
                # Validate template structure
                if not isinstance(template_data, dict):
                    messagebox.showerror("Error", "Invalid template file format.")
                    return
                
                # Populate fields
                self.hosts_entry.delete(0, tk.END)
                self.hosts_entry.insert(0, template_data.get('contributors', ''))
                
                self.show_entry.delete(0, tk.END)
                self.show_entry.insert(0, template_data.get('show_name', ''))
                
                # Load cover art if path exists and file exists
                cover_path = template_data.get('cover_art_path', '')
                if cover_path and os.path.exists(cover_path):
                    self.show_cover_preview(cover_path)
                else:
                    # Clear cover preview if path doesn't exist
                    self.clear_cover_preview()
                
                self.display_output(f"✅ Template loaded: {os.path.basename(file_path)}")
                
            except json.JSONDecodeError:
                messagebox.showerror("Error", "Invalid JSON in template file.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load template: {e}")

    def toggle_autoload(self):
        """Toggle autoload feature on/off"""
        if not self.autoload_enabled:
            # Turn autoload on - show template selection
            self.select_autoload_template()
        else:
            # Turn autoload off
            self.autoload_enabled = False
            self.autoload_template_path = None
            self.update_autoload_button_style()
            self.display_output("🔴 Autoload disabled")

    def select_autoload_template(self):
        """Select a template for autoload"""
        file_path = filedialog.askopenfilename(
            title="Select Template for Autoload",
            filetypes=[("JSON Template Files", "*.json"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                # Validate the template file
                with open(file_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                
                if not isinstance(template_data, dict):
                    messagebox.showerror("Error", "Invalid template file format.")
                    return
                
                # Enable autoload
                self.autoload_enabled = True
                self.autoload_template_path = file_path
                
                # Save autoload preference
                self.save_autoload_preference(file_path)
                
                self.update_autoload_button_style()
                self.display_output(f"🔵 Autoload enabled: {os.path.basename(file_path)}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Invalid template file: {e}")

    def save_autoload_preference(self, template_path):
        """Save autoload preference to app config"""
        try:
            autoload_config = {
                "enabled": True,
                "template_path": template_path,
                "last_updated": datetime.now().isoformat()
            }
            
            config_path = self.template_manager.config_dir / "autoload.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(autoload_config, f, indent=2)
                
        except Exception as e:
            print(f"Warning: Could not save autoload preference: {e}")

    def load_autoload_preference(self):
        """Load autoload preference on app startup"""
        try:
            config_path = self.template_manager.config_dir / "autoload.json"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                if config.get('enabled') and config.get('template_path'):
                    template_path = config['template_path']
                    if os.path.exists(template_path):
                        self.autoload_enabled = True
                        self.autoload_template_path = template_path
                        self.update_autoload_button_style()
                        return True
                        
        except Exception as e:
            print(f"Warning: Could not load autoload preference: {e}")
        
        return False

    def auto_load_template(self):
        """Automatically load the selected template on startup"""
        if self.autoload_enabled and self.autoload_template_path:
            try:
                with open(self.autoload_template_path, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                
                # Populate fields
                self.hosts_entry.delete(0, tk.END)
                self.hosts_entry.insert(0, template_data.get('contributors', ''))
                
                self.show_entry.delete(0, tk.END)
                self.show_entry.insert(0, template_data.get('show_name', ''))
                
                # Load cover art if path exists
                cover_path = template_data.get('cover_art_path', '')
                if cover_path and os.path.exists(cover_path):
                    self.show_cover_preview(cover_path)
                
                self.display_output(f"🔵 Autoloaded template: {os.path.basename(self.autoload_template_path)}")
                
            except Exception as e:
                self.display_output(f"⚠️ Failed to autoload template: {e}")

    def update_autoload_button_style(self):
        """Update the autoload button appearance based on state"""
        if self.autoload_enabled:
            # macOS-style blue button when enabled
            self.autoload_btn.config(
                bg="SystemButtonFace",        # macOS blue
                fg="SystemButtonText",
                activebackground="SystemButtonFace",
                activeforeground="SystemButtonText"
            )
            self.autoload_btn.config(text="Autoload: ON")
        else:
            # Default button style when disabled
            self.autoload_btn.config(
                bg="SystemButtonFace",
                fg="SystemButtonText", 
                activebackground="SystemButtonFace",
                activeforeground="SystemButtonText"
            )
            self.autoload_btn.config(text="Autoload: OFF")

    def clear_cover_preview(self):
        """Clear the cover art preview"""
        self.cover_canvas.delete("all")
        self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
        self.cover_canvas.create_text(
            COVER_PREVIEW_SIZE // 2, 
            COVER_PREVIEW_SIZE // 2,
            text="Click to select\ncover art", 
            fill="gray", 
            anchor="center"
        )
        self.cover_image = None
        if hasattr(self, 'current_cover_path'):
            delattr(self, 'current_cover_path')

    # === Existing Methods (Updated) ===

    def open_calendar(self):
        """Open calendar dialog for date selection"""
        dialog = CalendarDialog(self.master)
        self.master.wait_window(dialog.top)
        
        if dialog.result:
            self.date_entry.delete(0, tk.END)
            self.date_entry.insert(0, dialog.result)

    def browse_file(self):
        """Browse for MP3 file"""
        file_path = filedialog.askopenfilename(filetypes=[("MP3 Files", "*.mp3")])
        if file_path:
            # Store the file path internally but don't show it in the UI
            self.current_mp3_path = file_path
            self.display_output(f"Selected MP3 file: {os.path.basename(file_path)}")

    def browse_cover(self, event=None):
        """Browse for cover art image (can be called from click event)"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Image Files", "*.jpg *.jpeg *.png")]
        )
        if file_path:
            self.show_cover_preview(file_path)

    def show_cover_preview(self, cover_path: str):
        """Display cover art preview"""
        self.cover_canvas.delete("all")
        try:
            img = Image.open(cover_path)
            img.thumbnail((COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE), Image.LANCZOS)
            
            self.cover_image = ImageTk.PhotoImage(img)
            
            # Calculate position to center the image
            x = (COVER_PREVIEW_SIZE - self.cover_image.width()) // 2
            y = (COVER_PREVIEW_SIZE - self.cover_image.height()) // 2
            
            # Create image on canvas
            self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
            self.cover_canvas.create_image(x, y, anchor="nw", image=self.cover_image)
            
            # Store the cover path for later use
            self.current_cover_path = cover_path
            
        except Exception as e:
            # Clear canvas and show error message
            self.cover_canvas.create_rectangle(0, 0, COVER_PREVIEW_SIZE, COVER_PREVIEW_SIZE, fill="white", outline="")
            self.cover_canvas.create_text(
                COVER_PREVIEW_SIZE // 2, 
                COVER_PREVIEW_SIZE // 2,
                text="Click to select\ncover art", 
                fill="gray", 
                anchor="center"
            )
            self.cover_image = None
            if hasattr(self, 'current_cover_path'):
                delattr(self, 'current_cover_path')

    def clear_all(self):
        """Clear all input fields and reset the form (but keep autoload settings)"""
        # Clear all entry fields
        self.hosts_entry.delete(0, tk.END)
        self.show_entry.delete(0, tk.END)
        self.episode_entry.delete(0, tk.END)
        self.episode_title_entry.delete(0, tk.END)
        self.date_entry.delete(0, tk.END)
        
        # Reset field backgrounds to white
        for entry in [self.hosts_entry, self.show_entry, 
                     self.episode_entry, self.episode_title_entry, 
                     self.date_entry]:
            entry.config(bg="white")
        
        # Clear cover preview
        self.clear_cover_preview()
        
        # Clear stored file paths (but keep autoload template path)
        if hasattr(self, 'current_mp3_path'):
            delattr(self, 'current_mp3_path')
        
        # Clear output box
        self.output_box.config(state="normal")
        self.output_box.delete(1.0, tk.END)
        self.output_box.config(state="disabled")
        
        # Set focus to first field
        self.hosts_entry.focus_set()

    def get_input_values(self) -> Dict[str, str]:
        """Get all input values from the form"""
        return {
            "file": getattr(self, 'current_mp3_path', ""),
            "hosts": self.hosts_entry.get(),
            "show": self.show_entry.get(),
            "episode": self.episode_entry.get(),
            "episode_title": self.episode_title_entry.get(),
            "date": self.date_entry.get(),
            "cover": getattr(self, 'current_cover_path', ""),
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
            return ValidationResult(False, "Please select a valid MP3 file using the 'Select MP3 File' button.")

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
        date_result = self.engine.get_broadcast_date(values["date"])
        self.set_field_validation_style(self.date_entry, values["date"], date_result.success)
        
        if not date_result.success:
            return ValidationResult(False, f"Broadcast date error: {date_result.message}")

        # Validate cover art (can be empty)
        cover_path = values["cover"]
        if cover_path:
            cover_result = self.engine.process_cover_art(cover_path)
            if not cover_result.success:
                return cover_result

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
            f"  Artist (Contributors): {tags.artist or '(empty)'}",
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
        for entry in [self.hosts_entry, self.show_entry, 
                     self.episode_entry, self.episode_title_entry, 
                     self.date_entry]:
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
        if not messagebox.askyesno("Confirm", "Are you sure you want to save changes?"):
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
    # Uncomment the line below to test the template system
    # test_template_system()
    
    main()
