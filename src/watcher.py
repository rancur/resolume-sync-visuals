"""
Watch mode — monitor a directory for new music files and auto-generate visuals.

Uses watchdog for filesystem events, processes files sequentially through the
full analysis -> generation -> composition -> Resolume export pipeline.
"""
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from queue import Queue, Empty

from rich.console import Console
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from .analyzer.audio import analyze_track
from .analyzer.genre import detect_genre_and_style
from .generator.engine import GenerationConfig, generate_visuals
from .composer.timeline import compose_timeline
from .resolume.export import create_resolume_deck, generate_resolume_osc_script
from .tracking.registry import RenderRegistry

logger = logging.getLogger("rsv.watcher")

MUSIC_EXTENSIONS = {".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"}

# Seconds to wait after a file appears before processing (let copies finish)
SETTLE_DELAY = 5.0


class MusicFileHandler(FileSystemEventHandler):
    """Watches for new music files and queues them for processing."""

    def __init__(self, queue: Queue, registry: RenderRegistry, style: str):
        super().__init__()
        self.queue = queue
        self.registry = registry
        self.style = style

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in MUSIC_EXTENSIONS:
            logger.debug(f"Detected new file: {path.name}")
            self.queue.put(path)


def _sanitize_name(name: str) -> str:
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(char, '_')
    return name.strip().strip('.')


def _load_style(style_name: str) -> dict:
    """Load a style configuration by name."""
    import yaml

    style_dir = Path(__file__).parent.parent / "config" / "styles"
    style_file = style_dir / f"{style_name}.yaml"
    if not style_file.exists():
        style_file = Path(style_name)
        if not style_file.exists():
            raise FileNotFoundError(f"Style not found: {style_name}")
    with open(style_file) as f:
        return yaml.safe_load(f)


def _process_file(
    file_path: Path,
    style: str,
    quality: str,
    output_dir: Path,
    registry: RenderRegistry,
    console: Console,
):
    """Process a single music file through the full pipeline."""
    console.print(f"\n[bold cyan]Processing:[/bold cyan] {file_path.name}")

    # Check registry — skip if already rendered with this style/quality
    audio_hash = registry.hash_audio(str(file_path))
    existing = registry.get_track_renders()
    for tr in existing:
        if (
            tr["audio_hash"] == audio_hash
            and tr["style"] == style
            and tr["quality"] == quality
            and tr["status"] == "completed"
        ):
            console.print(f"  [dim]Skipping (already rendered): {file_path.name}[/dim]")
            return

    # Resolve style — "auto" uses genre detection
    resolved_style = style
    if style == "auto":
        genre_hint, resolved_style = detect_genre_and_style(str(file_path))
        console.print(f"  [magenta]Auto-detected genre:[/magenta] {genre_hint} -> style: {resolved_style}")

    style_config = _load_style(resolved_style)
    console.print(f"  [bold]Style:[/bold] {style_config.get('name', resolved_style)}")

    # Analyze
    console.print("  Analyzing audio...")
    analysis = analyze_track(str(file_path))
    console.print(
        f"  BPM: {analysis.bpm:.1f} | Phrases: {len(analysis.phrases)} | "
        f"Structure: {' -> '.join(p.label for p in analysis.phrases)}"
    )

    # Generate
    track_dir = output_dir / _sanitize_name(analysis.title)
    track_dir.mkdir(parents=True, exist_ok=True)

    gen_config = GenerationConfig(
        style_name=resolved_style,
        style_config=style_config,
        backend="openai",
        quality=quality,
        output_dir=str(track_dir / "raw"),
        cache_dir=str(track_dir / ".cache"),
    )

    analysis_dict = analysis.to_dict()

    console.print(f"  Generating visuals ({len(analysis.phrases)} phrases)...")
    clips = generate_visuals(analysis_dict, gen_config)
    console.print(f"  Generated {len(clips)} clips")

    # Compose + Resolume export
    console.print("  Composing timeline...")
    composition = compose_timeline(analysis_dict, clips, track_dir)
    create_resolume_deck(composition, track_dir)
    generate_resolume_osc_script(composition, track_dir / "osc_trigger.py")

    console.print(f"  [green]Done -> {track_dir}[/green]")


def run_watcher(
    directory: str,
    style: str = "auto",
    quality: str = "high",
    output_dir: str = "output",
    poll_interval: int = 10,
):
    """
    Watch a directory for new music files and auto-generate visuals.

    Args:
        directory: Directory to watch for new music files.
        style: Visual style preset, or "auto" for genre-based detection.
        quality: Render quality (draft/standard/high).
        output_dir: Base output directory for generated visuals.
        poll_interval: Polling interval in seconds for the observer.
    """
    console = Console()
    watch_dir = Path(directory).resolve()

    if not watch_dir.is_dir():
        console.print(f"[red]Not a directory: {watch_dir}[/red]")
        sys.exit(1)

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    registry = RenderRegistry()
    file_queue: Queue[Path] = Queue()
    shutdown_event = threading.Event()

    console.print(f"[bold green]Watch mode started[/bold green]")
    console.print(f"  Directory: {watch_dir}")
    console.print(f"  Style: {style}")
    console.print(f"  Quality: {quality}")
    console.print(f"  Output: {output_path}")
    console.print(f"  Poll interval: {poll_interval}s")
    console.print(f"  Extensions: {', '.join(sorted(MUSIC_EXTENSIONS))}")
    console.print(f"\n  Press Ctrl+C to stop.\n")

    handler = MusicFileHandler(file_queue, registry, style)

    # Use PollingObserver for reliability across filesystems (NFS, SMB, etc.)
    observer = PollingObserver(timeout=poll_interval)
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    # Graceful shutdown on Ctrl+C
    def _signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down watcher...[/yellow]")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        while not shutdown_event.is_set():
            try:
                file_path = file_queue.get(timeout=1.0)
            except Empty:
                continue

            # Wait for file copy to complete
            console.print(f"[dim]New file detected: {file_path.name} — waiting {SETTLE_DELAY}s for copy to finish...[/dim]")
            time.sleep(SETTLE_DELAY)

            if not file_path.exists():
                console.print(f"[dim]File disappeared, skipping: {file_path.name}[/dim]")
                continue

            try:
                _process_file(
                    file_path=file_path,
                    style=style,
                    quality=quality,
                    output_dir=output_path,
                    registry=registry,
                    console=console,
                )
            except Exception as e:
                console.print(f"[red]Error processing {file_path.name}: {e}[/red]")
                logger.exception(f"Failed to process {file_path}")

    finally:
        observer.stop()
        observer.join()
        console.print("[bold green]Watcher stopped.[/bold green]")
