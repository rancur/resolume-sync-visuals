"""
CLI for resolume-sync-visuals.
Usage:
    rsv analyze <file>           — Analyze a track and print BPM/structure
    rsv generate <file>          — Generate visuals for a single track
    rsv bulk <directory>         — Process all tracks in a directory
    rsv scan <directory>         — Scan music library and show metadata
    rsv styles                   — List available visual styles
    rsv watch <directory>        — Watch a directory for new music and auto-generate
"""
import json
import logging
import os
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel

from .analyzer.audio import analyze_track
from .analyzer.genre import detect_genre_and_style, get_auto_mix_styles
from .scanner import scan_library, read_track_metadata, read_engine_db, read_rekordbox_xml
from .generator.engine import GenerationConfig, generate_visuals, resolve_phrase_style
from .generator.batch import (
    prepare_batch,
    submit_batch,
    check_batch,
    download_batch_results,
    process_batch_results,
    list_batches,
    estimate_batch_cost,
)
from .composer.timeline import compose_timeline
from .composer.montage import create_montage
from .composer.thumbnails import create_thumbnail_grid
from .resolume.export import create_resolume_deck, generate_resolume_osc_script
from .tracking import BulkProgress, CostTracker, RenderRegistry, RunLogger

console = Console()
logger = logging.getLogger("rsv")


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_style(style_name: str) -> dict:
    """Load a style configuration by name."""
    # Check built-in styles
    style_dir = Path(__file__).parent.parent / "config" / "styles"
    style_file = style_dir / f"{style_name}.yaml"

    if not style_file.exists():
        # Check if it's a path
        style_file = Path(style_name)
        if not style_file.exists():
            console.print(f"[red]Style not found: {style_name}[/red]")
            console.print(f"Available styles: {', '.join(_list_styles())}")
            sys.exit(1)

    with open(style_file) as f:
        return yaml.safe_load(f)


def _list_styles() -> list[str]:
    """List available style names."""
    style_dir = Path(__file__).parent.parent / "config" / "styles"
    if not style_dir.exists():
        return []
    return sorted(f.stem for f in style_dir.glob("*.yaml"))


def _load_config(config_path: str | None) -> dict:
    """Load default config, optionally overridden by user config."""
    default_path = Path(__file__).parent.parent / "config" / "default.yaml"
    config = {}
    if default_path.exists():
        with open(default_path) as f:
            config = yaml.safe_load(f) or {}

    if config_path:
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
            _deep_merge(config, user_config)

    return config


def _deep_merge(base: dict, override: dict):
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--config", "-c", type=str, default=None, help="Config file path")
@click.option("--budget", type=float, default=None, help="Budget limit in USD (e.g. 10.00)")
@click.pass_context
def main(ctx, verbose, config, budget):
    """Resolume Sync Visuals — AI-powered beat-synced visual loops."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(config)
    ctx.obj["verbose"] = verbose
    ctx.obj["budget"] = budget


@main.command()
@click.pass_context
def check(ctx):
    """Validate environment -- dependencies, API keys, models, disk space."""
    from .validation import (
        check_dependencies,
        validate_api_key,
        check_mood_models,
        check_disk_space,
    )

    console.print("\n[bold cyan]Environment Check[/bold cyan]\n")
    all_ok = True

    # Dependencies (ffmpeg, ffprobe, python)
    deps = check_dependencies()
    for tool, info in deps.items():
        ok = info["available"]
        ver = info["version"]
        if tool == "python":
            label = f"Python >= 3.9 ({ver})"
        else:
            label = f"{tool} ({ver})" if ver else tool
        if ok:
            console.print(f"  [green]\u2713[/green] {label}")
        else:
            console.print(f"  [red]\u2717[/red] {label}")
            all_ok = False

    # API keys
    for backend in ("openai", "replicate"):
        ok, msg = validate_api_key(backend)
        env_var = "OPENAI_API_KEY" if backend == "openai" else "REPLICATE_API_TOKEN"
        if ok:
            console.print(f"  [green]\u2713[/green] {env_var}")
        else:
            console.print(f"  [red]\u2717[/red] {env_var} -- {msg}")
            # Not fatal -- user may only use one backend
            if backend == "openai":
                all_ok = False

    # Mood models
    ok, msg = check_mood_models()
    if ok:
        console.print(f"  [green]\u2713[/green] Essentia mood models -- {msg}")
    else:
        console.print(f"  [yellow]![/yellow] Essentia mood models -- {msg}")

    # Disk space
    output_dir = ctx.obj.get("config", {}).get("output_dir", "output")
    ok, available = check_disk_space(output_dir, required_mb=500)
    if ok:
        console.print(f"  [green]\u2713[/green] Disk space -- {available:,} MB available")
    else:
        console.print(f"  [red]\u2717[/red] Disk space -- {available:,} MB available (need 500 MB)")
        all_ok = False

    # Output directory writable
    out_path = Path(output_dir)
    try:
        out_path.mkdir(parents=True, exist_ok=True)
        test_file = out_path / ".rsv_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        console.print(f"  [green]\u2713[/green] Output directory writable -- {out_path}")
    except Exception as e:
        console.print(f"  [red]\u2717[/red] Output directory not writable -- {e}")
        all_ok = False

    console.print()
    if all_ok:
        console.print("[bold green]All checks passed.[/bold green]\n")
    else:
        console.print("[bold red]Some checks failed. Fix issues above before generating.[/bold red]\n")


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--phrase-beats", "-p", type=int, default=None, help="Override phrase length in beats")
@click.option("--bpm", type=float, default=None, help="Override BPM (skip auto-detection)")
@click.option("--max-phrases", type=int, default=32, help="Max phrases (excess merged, default: 32)")
@click.option("--output", "-o", type=str, default=None, help="Output JSON path")
@click.pass_context
def analyze(ctx, file, phrase_beats, bpm, max_phrases, output):
    """Analyze a music track -- BPM, beats, phrases, structure."""
    console.print(f"\n[bold cyan]Analyzing:[/bold cyan] {Path(file).name}\n")

    with console.status("[bold green]Analyzing audio..."):
        analysis = analyze_track(file, phrase_beats=phrase_beats, bpm_override=bpm,
                                 max_phrases=max_phrases)

    # Display results
    table = Table(title="Track Analysis")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Title", analysis.title)
    table.add_row("Duration", f"{analysis.duration:.1f}s ({analysis.duration/60:.1f}m)")
    table.add_row("BPM", f"{analysis.bpm:.1f}")
    table.add_row("Time Signature", f"{analysis.time_signature}/4")
    table.add_row("Total Beats", str(len(analysis.beats)))
    table.add_row("Phrases", str(len(analysis.phrases)))
    table.add_row("Phrase Length", f"{analysis.phrase_duration_beats} beats")

    console.print(table)

    # Phrase breakdown
    console.print("\n[bold]Phrase Structure:[/bold]")
    phrase_table = Table()
    phrase_table.add_column("#", style="dim")
    phrase_table.add_column("Label", style="cyan")
    phrase_table.add_column("Start", style="green")
    phrase_table.add_column("End", style="green")
    phrase_table.add_column("Beats", style="yellow")
    phrase_table.add_column("Energy", style="magenta")

    for i, p in enumerate(analysis.phrases):
        energy_bar = "█" * int(p.energy * 10) + "░" * (10 - int(p.energy * 10))
        phrase_table.add_row(
            str(i),
            p.label,
            f"{p.start:.1f}s",
            f"{p.end:.1f}s",
            str(p.beats),
            f"{energy_bar} {p.energy:.2f}",
        )

    console.print(phrase_table)

    # Save JSON if requested
    if output:
        out_path = Path(output)
        analysis.to_json(out_path)
        console.print(f"\n[green]Analysis saved to:[/green] {out_path}")
    else:
        # Print JSON summary
        console.print(Panel(
            json.dumps({
                "bpm": analysis.bpm,
                "duration": analysis.duration,
                "phrases": len(analysis.phrases),
                "structure": [p.label for p in analysis.phrases],
            }, indent=2),
            title="Summary JSON",
        ))


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--style", "-s", type=str, default="abstract", help="Visual style preset")
@click.option("--backend", "-b", type=click.Choice(["openai", "replicate"]), default="openai")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--output-dir", "-o", type=str, default="output", help="Output directory")
@click.option("--loop-beats", "-l", type=int, default=0, help="Loop duration in beats (0=auto)")
@click.option("--phrase-beats", "-p", type=int, default=None, help="Override phrase length")
@click.option("--bpm", type=float, default=None, help="Override BPM (skip auto-detection)")
@click.option("--width", type=int, default=1920, help="Video width")
@click.option("--height", type=int, default=1080, help="Video height")
@click.option("--fps", type=int, default=30, help="Video FPS")
@click.option("--strobe", is_flag=True, default=False, help="Enable strobe flash on drops")
@click.option("--strobe-intensity", type=float, default=0.8, help="Strobe intensity 0.0-1.0")
@click.option("--dry-run", is_flag=True, default=False, help="Analyze only, show cost estimate")
@click.option("--montage", is_flag=True, default=False, help="Create preview montage with audio")
@click.option("--style-drop", type=str, default=None, help="Style override for drop phrases")
@click.option("--style-buildup", type=str, default=None, help="Style override for buildup phrases")
@click.option("--style-breakdown", type=str, default=None, help="Style override for breakdown phrases")
@click.option("--style-intro", type=str, default=None, help="Style override for intro/outro phrases")
@click.option("--thumbnails", is_flag=True, default=False, help="Generate thumbnail contact sheet")
@click.option("--video-model", type=str, default=None,
              help="Use text-to-video model (e.g. wan2.1-480p, wan2.1-720p, minimax-live)")
@click.pass_context
def generate(ctx, file, style, backend, quality, output_dir, loop_beats,
             phrase_beats, bpm, width, height, fps, strobe, strobe_intensity, dry_run, montage,
             style_drop, style_buildup, style_breakdown, style_intro, thumbnails, video_model):
    """Generate beat-synced visuals for a single track."""
    file_path = Path(file)
    console.print(f"\n[bold cyan]Processing:[/bold cyan] {file_path.name}")

    # Resolve "auto" style via genre detection
    is_auto_mix = (style == "auto-mix")
    if style == "auto":
        with console.status("[bold green]Detecting genre..."):
            genre_hint, style = detect_genre_and_style(str(file_path))
        console.print(f"[magenta]Auto-detected genre:[/magenta] {genre_hint} -> style: {style}")

    # Handle auto-mix: randomized per-phrase styles seeded by audio hash
    style_overrides = None
    if is_auto_mix:
        audio_hash = _compute_audio_hash(str(file_path))
        mix_styles = get_auto_mix_styles(seed=audio_hash)
        console.print(f"[magenta]Auto-mix styles:[/magenta] {mix_styles}")
        # Use drop style as the base/default
        style = mix_styles["drop"]
        style_config = _load_style(style)
        style_overrides = {label: _load_style(sname) for label, sname in mix_styles.items()}
        override_desc = ", ".join(f"{k}={v.get('name', k)}" for k, v in style_overrides.items())
        console.print(f"[bold]Style overrides:[/bold] {override_desc}")
    else:
        # Load style
        style_config = _load_style(style)
        console.print(f"[bold]Style:[/bold] {style_config.get('name', style)} — {style_config.get('description', '')}")

        # Build per-phrase style overrides
        style_overrides = _build_style_overrides(style_drop, style_buildup, style_breakdown, style_intro)
        if style_overrides:
            override_desc = ", ".join(f"{k}={v.get('name', k)}" for k, v in style_overrides.items())
            console.print(f"[bold]Style overrides:[/bold] {override_desc}")

    # Step 1: Analyze
    console.print("\n[bold yellow]Step 1:[/bold yellow] Analyzing audio...")
    with console.status("[bold green]Detecting BPM, beats, phrases..."):
        analysis = analyze_track(file, phrase_beats=phrase_beats, bpm_override=bpm)

    console.print(f"  BPM: {analysis.bpm:.1f} | Phrases: {len(analysis.phrases)} | "
                  f"Structure: {' → '.join(p.label for p in analysis.phrases)}")

    # Step 1b: Mood analysis
    try:
        from .analyzer.mood import analyze_mood
        with console.status("[bold green]Analyzing mood and emotion..."):
            mood = analyze_mood(file)
        analysis.mood = mood.to_dict()
        console.print(f"  Mood: {mood.dominant_mood} ({mood.quadrant}) | "
                      f"Valence: {mood.valence:.2f} | Arousal: {mood.arousal:.2f}")
        console.print(f"  Feel: {mood.mood_descriptor}")
    except Exception as e:
        logger.debug(f"Mood analysis unavailable: {e}")
        console.print(f"  [dim]Mood analysis skipped ({e.__class__.__name__})[/dim]")

    # Cost estimation
    n_phrases = len(analysis.phrases)
    # ~3 keyframes per phrase average, each = 1 API call
    est_api_calls = n_phrases * 3
    if backend == "openai":
        cost_per_call = 0.08 if quality == "high" else 0.04  # DALL-E 3 HD vs standard
    else:
        cost_per_call = 0.003  # Flux Schnell on Replicate
    est_cost = est_api_calls * cost_per_call

    console.print(f"  Estimated: ~{est_api_calls} API calls, ~${est_cost:.2f} "
                  f"({backend}, {quality} quality)")

    if dry_run:
        console.print(Panel(
            f"[yellow]Dry run — no visuals generated[/yellow]\n\n"
            f"Track: {analysis.title}\n"
            f"BPM: {analysis.bpm:.1f}\n"
            f"Phrases: {n_phrases}\n"
            f"Estimated API calls: ~{est_api_calls}\n"
            f"Estimated cost: ~${est_cost:.2f}",
            title="Cost Estimate",
        ))
        return

    # Step 2: Generate visuals
    console.print(f"\n[bold yellow]Step 2:[/bold yellow] Generating visuals ({n_phrases} phrases)...")

    # Per-track output directory
    track_dir = Path(output_dir) / _sanitize_name(analysis.title)
    track_dir.mkdir(parents=True, exist_ok=True)

    gen_config = GenerationConfig(
        width=width,
        height=height,
        fps=fps,
        style_name=style,
        style_config=style_config,
        backend=backend,
        loop_duration_beats=loop_beats,
        quality=quality,
        output_dir=str(track_dir / "raw"),
        cache_dir=str(track_dir / ".cache"),
        strobe_enabled=strobe,
        strobe_intensity=strobe_intensity,
        style_overrides=style_overrides,
        video_model=video_model,
    )

    analysis_dict = analysis.to_dict()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating...", total=len(analysis.phrases))

        def on_progress(current, total, msg):
            progress.update(task, completed=current, description=msg)

        # Initialize tracking
        budget = ctx.obj.get("budget")
        cost_tracker = CostTracker(budget_limit=budget)
        render_registry = RenderRegistry()

        clips = generate_visuals(
            analysis_dict, gen_config,
            progress_callback=on_progress,
            cost_tracker=cost_tracker,
            render_registry=render_registry,
        )
        progress.update(task, completed=len(analysis.phrases))

    # Show session cost summary
    session = cost_tracker.get_session_summary()
    console.print(f"  Generated {len(clips)} clips | "
                  f"API calls: {session['session_api_calls']} | "
                  f"Cost: ${session['session_cost']:.2f} | "
                  f"Cache hits: {session['session_cache_hits']}")

    # Step 3: Compose timeline
    console.print(f"\n[bold yellow]Step 3:[/bold yellow] Composing timeline...")
    with console.status("[bold green]Building loops and organizing output..."):
        composition = compose_timeline(analysis_dict, clips, track_dir)

    # Step 4: Create Resolume deck
    console.print(f"\n[bold yellow]Step 4:[/bold yellow] Creating Resolume deck...")
    with console.status("[bold green]Organizing for Resolume Arena..."):
        resolume_dir = create_resolume_deck(composition, track_dir)
        osc_script_path = track_dir / "osc_trigger.py"
        generate_resolume_osc_script(composition, osc_script_path)

    # Step 5: Create montage (optional)
    montage_path = None
    if montage:
        console.print(f"\n[bold yellow]Step 5:[/bold yellow] Creating preview montage...")
        with console.status("[bold green]Building montage with audio..."):
            montage_path = track_dir / f"{_sanitize_name(analysis.title)}_montage.mp4"
            create_montage(clips, file, montage_path, analysis_dict)
        console.print(f"  Montage: {montage_path}")

    # Step 6: Create thumbnail grid (optional)
    thumbnail_path = None
    if thumbnails:
        from .composer.thumbnails import create_thumbnail_grid
        step_num = 6
        console.print(f"\n[bold yellow]Step {step_num}:[/bold yellow] Creating thumbnail grid...")
        with console.status("[bold green]Building contact sheet..."):
            thumbnail_path = track_dir / f"{_sanitize_name(analysis.title)}_thumbnails.png"
            create_thumbnail_grid(clips, analysis_dict, thumbnail_path)
        console.print(f"  Thumbnails: {thumbnail_path}")

    # Summary
    console.print(Panel(
        f"[green]Track:[/green] {analysis.title}\n"
        f"[green]BPM:[/green] {analysis.bpm:.1f}\n"
        f"[green]Clips:[/green] {len(composition['clips'])}\n"
        f"[green]Loops:[/green] {len(composition['loops'])}\n"
        f"[green]Output:[/green] {track_dir}\n"
        f"[green]Resolume:[/green] {resolume_dir}\n"
        f"[green]OSC Script:[/green] {osc_script_path}"
        + (f"\n[green]Montage:[/green] {montage_path}" if montage_path else "")
        + (f"\n[green]Thumbnails:[/green] {thumbnail_path}" if thumbnail_path else ""),
        title="[bold green]Generation Complete[/bold green]",
    ))


@main.command()
@click.argument("directory", type=click.Path(exists=True))
@click.option("--style", "-s", type=str, default="abstract", help="Visual style preset")
@click.option("--backend", "-b", type=click.Choice(["openai", "replicate"]), default="openai")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--output-dir", "-o", type=str, default="output", help="Output directory")
@click.option("--loop-beats", "-l", type=int, default=0, help="Loop duration in beats (0=auto)")
@click.option("--max-concurrent", type=int, default=2, help="Max concurrent tracks")
@click.option("--skip-existing", is_flag=True, default=True, help="Skip already processed tracks")
@click.option("--batch", "use_batch", is_flag=True, default=False, help="Queue for OpenAI Batch API (50% cost savings)")
@click.option("--resume", is_flag=True, default=False, help="Resume the last incomplete run for this directory")
@click.pass_context
def bulk(ctx, directory, style, backend, quality, output_dir, loop_beats,
         max_concurrent, skip_existing, use_batch, resume):
    """Process all music files in a directory."""
    config = ctx.obj["config"]
    extensions = config.get("bulk", {}).get("file_extensions",
                                             [".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"])

    dir_path = Path(directory)
    files = []
    for ext in extensions:
        files.extend(dir_path.rglob(f"*{ext}"))

    files = sorted(files)

    if not files:
        console.print(f"[red]No music files found in {directory}[/red]")
        console.print(f"Supported extensions: {', '.join(extensions)}")
        return

    # Progress persistence
    progress_tracker = BulkProgress()
    run_logger = RunLogger()
    norm_dir = str(Path(directory).resolve())

    # Resume mode: find last incomplete run and skip already-done files
    resume_run_id = None
    already_done: set[str] = set()
    if resume:
        resume_run_id = progress_tracker.get_latest_run(norm_dir)
        if resume_run_id:
            already_done = progress_tracker.get_completed_files(resume_run_id)
            status = progress_tracker.get_run_status(resume_run_id)
            console.print(f"[bold yellow]Resuming run {resume_run_id}:[/bold yellow] "
                          f"{status['completed']} done, {status['failed']} failed, "
                          f"{status['remaining']} remaining")
        else:
            console.print("[dim]No incomplete run found for this directory, starting fresh.[/dim]")

    console.print(f"\n[bold cyan]Bulk Processing:[/bold cyan] {len(files)} tracks in {directory}")
    console.print(f"[bold]Style:[/bold] {style} | [bold]Backend:[/bold] {backend} | "
                  f"[bold]Quality:[/bold] {quality}\n")

    # List files
    for i, f in enumerate(files):
        console.print(f"  {i+1:3d}. {f.name}")

    console.print()

    if style not in ("auto", "auto-mix"):
        style_config = _load_style(style)
    else:
        style_config = None  # resolved per-track below
    output_base = Path(output_dir)

    # Batch mode: analyze all tracks, prepare JSONL for OpenAI Batch API
    if use_batch:
        console.print("[bold yellow]Batch mode:[/bold yellow] Preparing requests for OpenAI Batch API (50% cost savings)\n")
        analysis_list = []
        configs_list = []

        for i, file_path in enumerate(files):
            track_name = _sanitize_name(file_path.stem)
            console.print(f"  Analyzing {i+1}/{len(files)}: {file_path.name}...")
            try:
                track_style = style
                track_style_config = style_config
                track_style_overrides = None
                if style == "auto":
                    genre_hint, track_style = detect_genre_and_style(str(file_path))
                    console.print(f"    [magenta]Genre:[/magenta] {genre_hint} -> {track_style}")
                    track_style_config = _load_style(track_style)
                elif style == "auto-mix":
                    audio_hash = _compute_audio_hash(str(file_path))
                    mix_styles = get_auto_mix_styles(seed=audio_hash)
                    console.print(f"    [magenta]Auto-mix:[/magenta] {mix_styles}")
                    track_style = mix_styles["drop"]
                    track_style_config = _load_style(track_style)
                    track_style_overrides = {label: _load_style(sname) for label, sname in mix_styles.items()}

                analysis = analyze_track(str(file_path))
                analysis_dict = analysis.to_dict()
                analysis_list.append(analysis_dict)

                track_dir = output_base / track_name
                gen_config = GenerationConfig(
                    style_name=track_style,
                    style_config=track_style_config,
                    backend=backend,
                    loop_duration_beats=loop_beats,
                    quality=quality,
                    output_dir=str(track_dir / "raw"),
                    cache_dir=str(track_dir / ".cache"),
                    style_overrides=track_style_overrides,
                )
                configs_list.append(gen_config)
            except Exception as e:
                console.print(f"    [red]Failed to analyze: {e}[/red]")

        if not analysis_list:
            console.print("[red]No tracks analyzed successfully.[/red]")
            return

        # Estimate costs
        estimate = estimate_batch_cost(analysis_list, configs_list)
        console.print(f"\n[bold]Cost estimate:[/bold]")
        console.print(f"  Requests: {estimate['total_requests']}")
        console.print(f"  Sync cost:  ${estimate['sync_cost']:.2f}")
        console.print(f"  Batch cost: ${estimate['batch_cost']:.2f}")
        console.print(f"  [green]Savings:    ${estimate['savings']:.2f} (50%)[/green]")

        # Prepare JSONL
        jsonl_path = prepare_batch(analysis_list, configs_list, output_base)
        console.print(f"\n[green]JSONL prepared:[/green] {jsonl_path}")
        console.print(f"  {estimate['total_requests']} requests across {len(analysis_list)} tracks")
        console.print(f"\nTo submit: [cyan]rsv batch submit {jsonl_path}[/cyan]")

        # Save analysis data alongside JSONL for later processing
        batch_meta = {
            "analysis_list": analysis_list,
            "configs": [
                {
                    "style_name": c.style_name,
                    "quality": c.quality,
                    "output_dir": c.output_dir,
                    "cache_dir": c.cache_dir,
                    "width": c.width,
                    "height": c.height,
                    "fps": c.fps,
                    "backend": c.backend,
                    "loop_duration_beats": c.loop_duration_beats,
                }
                for c in configs_list
            ],
        }
        meta_path = output_base / "batch_metadata.json"
        meta_path.write_text(json.dumps(batch_meta, indent=2, default=str))
        console.print(f"[green]Metadata saved:[/green] {meta_path}")
        return

    # Start or reuse a progress run
    if resume_run_id:
        run_id = resume_run_id
    else:
        run_id = progress_tracker.start_run(norm_dir, style, quality, len(files))

    log_id = run_logger.start_run("bulk", {
        "directory": norm_dir, "style": style, "quality": quality,
        "backend": backend, "total_files": len(files), "run_id": run_id,
    })

    completed = 0
    failed = 0
    skipped = 0
    total_cost = 0.0

    for i, file_path in enumerate(files):
        track_name = _sanitize_name(file_path.stem)
        track_dir = output_base / track_name
        file_key = str(file_path.resolve())

        # Skip if already done in a resumed run
        if resume and file_key in already_done:
            console.print(f"[dim]Skipping (resumed): {file_path.name}[/dim]")
            skipped += 1
            continue

        # Skip if already processed
        if skip_existing and (track_dir / "metadata.json").exists():
            console.print(f"[dim]Skipping (exists): {file_path.name}[/dim]")
            progress_tracker.mark_file_skipped(run_id, file_key, "already exists")
            skipped += 1
            continue

        console.print(f"\n[bold]{'='*60}[/bold]")
        console.print(f"[bold cyan]Track {i+1}/{len(files)}:[/bold cyan] {file_path.name}")

        try:
            # Resolve auto style per track
            track_style = style
            track_style_config = style_config
            track_style_overrides = None
            if style == "auto":
                genre_hint, track_style = detect_genre_and_style(str(file_path))
                console.print(f"  [magenta]Auto-detected genre:[/magenta] {genre_hint} -> style: {track_style}")
                track_style_config = _load_style(track_style)
            elif style == "auto-mix":
                audio_hash = _compute_audio_hash(str(file_path))
                mix_styles = get_auto_mix_styles(seed=audio_hash)
                console.print(f"  [magenta]Auto-mix:[/magenta] {mix_styles}")
                track_style = mix_styles["drop"]
                track_style_config = _load_style(track_style)
                track_style_overrides = {label: _load_style(sname) for label, sname in mix_styles.items()}

            # Analyze
            analysis = analyze_track(str(file_path))
            console.print(f"  BPM: {analysis.bpm:.1f} | Phrases: {len(analysis.phrases)}")

            # Generate
            track_dir.mkdir(parents=True, exist_ok=True)
            gen_config = GenerationConfig(
                style_name=track_style,
                style_config=track_style_config,
                backend=backend,
                loop_duration_beats=loop_beats,
                quality=quality,
                output_dir=str(track_dir / "raw"),
                cache_dir=str(track_dir / ".cache"),
                style_overrides=track_style_overrides,
            )

            analysis_dict = analysis.to_dict()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Generating...", total=len(analysis.phrases))

                def on_progress(current, total, msg):
                    progress.update(task, completed=current, description=msg)

                clips = generate_visuals(analysis_dict, gen_config, progress_callback=on_progress)
                progress.update(task, completed=len(analysis.phrases))

            # Compose + Resolume export
            comp = compose_timeline(analysis_dict, clips, track_dir)
            create_resolume_deck(comp, track_dir)
            generate_resolume_osc_script(comp, track_dir / "osc_trigger.py")
            completed += 1

            track_cost = 0.0  # cost tracking handled by generate_visuals internally
            progress_tracker.mark_file_complete(
                run_id, file_key, str(track_dir), track_cost, len(clips))
            run_logger.log_track(
                log_id, file_path.name, "completed",
                bpm=analysis.bpm, phrases=len(analysis.phrases),
                clips=len(clips), cost=track_cost)
            console.print(f"  [green]✓ Complete — {len(clips)} clips[/green]")

        except Exception as e:
            failed += 1
            error_msg = str(e)
            progress_tracker.mark_file_failed(run_id, file_key, error_msg)
            run_logger.log_track(
                log_id, file_path.name, "failed",
                bpm=0, phrases=0, clips=0, cost=0, error=error_msg)
            console.print(f"  [red]✗ Failed: {e}[/red]")
            logger.exception(f"Failed to process {file_path}")

    # Complete the run
    progress_tracker.complete_run(run_id)
    run_logger.end_run(log_id, {
        "completed": completed, "failed": failed, "skipped": skipped,
        "total": len(files), "total_cost": total_cost,
    })

    # Final summary from progress DB
    run_status = progress_tracker.get_run_status(run_id)

    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(Panel(
        f"[green]Completed:[/green] {run_status.get('completed', completed)}/{len(files)}\n"
        f"[yellow]Skipped:[/yellow] {run_status.get('skipped', skipped)}/{len(files)}\n"
        f"[red]Failed:[/red] {run_status.get('failed', failed)}/{len(files)}\n"
        f"[blue]Run ID:[/blue] {run_id}\n"
        f"[blue]Output:[/blue] {output_base}",
        title="[bold]Bulk Processing Complete[/bold]",
    ))


@main.command("bulk-status")
@click.argument("directory", type=click.Path(exists=True), required=False)
@click.option("--run-id", type=str, default=None, help="Specific run ID to check")
@click.pass_context
def bulk_status(ctx, directory, run_id):
    """Show progress of current/last bulk run for a directory."""
    progress_tracker = BulkProgress()

    if run_id:
        status = progress_tracker.get_run_status(run_id)
    elif directory:
        norm_dir = str(Path(directory).resolve())
        latest_id = progress_tracker.get_latest_run(norm_dir)
        if not latest_id:
            console.print(f"[dim]No runs found for {directory}[/dim]")
            return
        status = progress_tracker.get_run_status(latest_id)
    else:
        console.print("[red]Provide a directory or --run-id[/red]")
        return

    if not status:
        console.print("[dim]Run not found.[/dim]")
        return

    total = status["total"]
    pct = ((status["completed"] + status["skipped"]) / total * 100) if total > 0 else 0
    status_color = "green" if status["status"] == "completed" else "yellow"

    console.print(Panel(
        f"[bold]Run ID:[/bold] {status['run_id']}\n"
        f"[bold]Directory:[/bold] {status['directory']}\n"
        f"[bold]Style:[/bold] {status['style']} | [bold]Quality:[/bold] {status['quality']}\n"
        f"[bold]Status:[/bold] [{status_color}]{status['status']}[/{status_color}]\n"
        f"[bold]Progress:[/bold] {pct:.0f}%\n"
        f"[green]Completed:[/green] {status['completed']}/{total}\n"
        f"[yellow]Skipped:[/yellow] {status['skipped']}/{total}\n"
        f"[red]Failed:[/red] {status['failed']}/{total}\n"
        f"[dim]Remaining:[/dim] {status['remaining']}\n"
        f"[green]Total Cost:[/green] ${status['total_cost']:.4f}\n"
        f"[green]Total Clips:[/green] {status['total_clips']}\n"
        f"[dim]Started:[/dim] {status['started_at']}",
        title="[bold cyan]Bulk Run Status[/bold cyan]",
    ))


@main.group()
@click.pass_context
def batch(ctx):
    """OpenAI Batch API commands (50% cost savings)."""
    pass


@batch.command("prepare")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--style", "-s", type=str, default="abstract", help="Visual style preset")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--output-dir", "-o", type=str, default="output", help="Output directory")
@click.option("--loop-beats", "-l", type=int, default=0, help="Loop duration in beats (0=auto)")
@click.pass_context
def batch_prepare(ctx, directory, style, quality, output_dir, loop_beats):
    """Analyze all tracks in a directory and prepare a JSONL batch file."""
    config = ctx.obj["config"]
    extensions = config.get("bulk", {}).get("file_extensions",
                                             [".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"])
    dir_path = Path(directory)
    files = []
    for ext in extensions:
        files.extend(dir_path.rglob(f"*{ext}"))
    files = sorted(files)
    if not files:
        console.print(f"[red]No music files found in {directory}[/red]")
        return
    console.print(f"\n[bold cyan]Batch Prepare:[/bold cyan] {len(files)} tracks")
    if style != "auto":
        style_config = _load_style(style)
    else:
        style_config = None
    output_base = Path(output_dir)
    analysis_list = []
    configs_list = []
    for i, file_path in enumerate(files):
        console.print(f"  Analyzing {i+1}/{len(files)}: {file_path.name}...")
        try:
            track_style = style
            track_style_config = style_config
            if style == "auto":
                genre_hint, track_style = detect_genre_and_style(str(file_path))
                console.print(f"    [magenta]Genre:[/magenta] {genre_hint} -> {track_style}")
                track_style_config = _load_style(track_style)
            analysis = analyze_track(str(file_path))
            analysis_dict = analysis.to_dict()
            analysis_list.append(analysis_dict)
            track_name = _sanitize_name(file_path.stem)
            track_dir = output_base / track_name
            gen_config = GenerationConfig(
                style_name=track_style,
                style_config=track_style_config,
                backend="openai",
                loop_duration_beats=loop_beats,
                quality=quality,
                output_dir=str(track_dir / "raw"),
                cache_dir=str(track_dir / ".cache"),
            )
            configs_list.append(gen_config)
        except Exception as e:
            console.print(f"    [red]Failed: {e}[/red]")
    if not analysis_list:
        console.print("[red]No tracks analyzed successfully.[/red]")
        return
    estimate = estimate_batch_cost(analysis_list, configs_list)
    console.print(f"\n[bold]Cost estimate:[/bold]")
    console.print(f"  Requests: {estimate['total_requests']}")
    console.print(f"  Sync cost:  ${estimate['sync_cost']:.2f}")
    console.print(f"  Batch cost: ${estimate['batch_cost']:.2f}")
    console.print(f"  [green]Savings:    ${estimate['savings']:.2f} (50%)[/green]")
    jsonl_path = prepare_batch(analysis_list, configs_list, output_base)
    console.print(f"\n[green]JSONL prepared:[/green] {jsonl_path}")
    batch_meta = {
        "analysis_list": analysis_list,
        "configs": [{"style_name": c.style_name, "quality": c.quality, "output_dir": c.output_dir, "cache_dir": c.cache_dir, "width": c.width, "height": c.height, "fps": c.fps, "backend": c.backend, "loop_duration_beats": c.loop_duration_beats} for c in configs_list],
    }
    meta_path = output_base / "batch_metadata.json"
    meta_path.write_text(json.dumps(batch_meta, indent=2, default=str))
    console.print(f"[green]Metadata saved:[/green] {meta_path}")
    console.print(f"\nNext: [cyan]rsv batch submit {jsonl_path}[/cyan]")


@batch.command("submit")
@click.argument("jsonl_file", type=click.Path(exists=True))
@click.pass_context
def batch_submit(ctx, jsonl_file):
    """Upload JSONL file and start an OpenAI batch."""
    console.print(f"[bold cyan]Submitting batch:[/bold cyan] {jsonl_file}")
    with open(jsonl_file) as f:
        n_requests = sum(1 for line in f if line.strip())
    console.print(f"  Requests: {n_requests}")
    with console.status("[bold green]Uploading and creating batch..."):
        bid = submit_batch(Path(jsonl_file))
    console.print(f"\n[green]Batch created:[/green] {bid}")
    console.print(f"\nCheck status: [cyan]rsv batch status {bid}[/cyan]")


@batch.command("status")
@click.argument("batch_id")
@click.pass_context
def batch_status(ctx, batch_id):
    """Check the status of an OpenAI batch."""
    with console.status("[bold green]Checking batch status..."):
        status = check_batch(batch_id)
    total = status["total"]
    completed = status["completed"]
    failed = status["failed"]
    pct = (completed / total * 100) if total > 0 else 0
    status_color = {"completed": "green", "failed": "red", "in_progress": "yellow", "validating": "cyan", "expired": "red", "cancelled": "dim"}.get(status["status"], "white")
    console.print(Panel(
        f"[bold]Batch:[/bold] {batch_id}\n"
        f"[bold]Status:[/bold] [{status_color}]{status['status']}[/{status_color}]\n"
        f"[bold]Progress:[/bold] {completed}/{total} ({pct:.0f}%)\n"
        f"[bold]Failed:[/bold] {failed}\n"
        f"[bold]Created:[/bold] {status.get('created_at', 'unknown')}\n"
        f"[bold]Expires:[/bold] {status.get('expires_at', 'unknown')}",
        title="[bold cyan]Batch Status[/bold cyan]",
    ))
    if status["status"] == "completed":
        console.print(f"\nDownload results: [cyan]rsv batch download {batch_id}[/cyan]")


@batch.command("download")
@click.argument("batch_id")
@click.option("--output-dir", "-o", type=str, default="output/batch_images", help="Output directory for images")
@click.pass_context
def batch_download(ctx, batch_id, output_dir):
    """Download completed batch results (images only)."""
    console.print(f"[bold cyan]Downloading batch:[/bold cyan] {batch_id}")
    with console.status("[bold green]Downloading batch results..."):
        results = download_batch_results(batch_id, Path(output_dir))
    success = sum(1 for r in results if r.get("image_path"))
    errors = sum(1 for r in results if r.get("error"))
    console.print(f"\n[green]Downloaded:[/green] {success} images")
    if errors:
        console.print(f"[red]Errors:[/red] {errors}")
    console.print(f"[blue]Output:[/blue] {output_dir}")


@batch.command("process")
@click.argument("batch_id")
@click.option("--output-dir", "-o", type=str, default="output", help="Output directory")
@click.option("--metadata", "-m", type=click.Path(exists=True), default=None, help="Path to batch_metadata.json")
@click.pass_context
def batch_process(ctx, batch_id, output_dir, metadata):
    """Download batch results and create videos (full pipeline)."""
    output_base = Path(output_dir)
    meta_path = Path(metadata) if metadata else output_base / "batch_metadata.json"
    if not meta_path.exists():
        console.print(f"[red]Metadata not found: {meta_path}[/red]")
        console.print("Run [cyan]rsv batch prepare[/cyan] first, or specify --metadata")
        return
    meta = json.loads(meta_path.read_text())
    analysis_list = meta["analysis_list"]
    configs_list = [GenerationConfig(style_name=c["style_name"], quality=c["quality"], output_dir=c["output_dir"], cache_dir=c["cache_dir"], width=c["width"], height=c["height"], fps=c["fps"], backend=c["backend"], loop_duration_beats=c["loop_duration_beats"]) for c in meta["configs"]]
    images_dir = output_base / "batch_images"
    console.print(f"[bold cyan]Downloading batch results...[/bold cyan]")
    with console.status("[bold green]Downloading images..."):
        results = download_batch_results(batch_id, images_dir)
    success = sum(1 for r in results if r.get("image_path"))
    errors = sum(1 for r in results if r.get("error"))
    console.print(f"  Downloaded: {success} images, {errors} errors")
    console.print(f"\n[bold cyan]Creating videos...[/bold cyan]")
    budget = ctx.obj.get("budget")
    cost_tracker = CostTracker(budget_limit=budget)
    render_registry = RenderRegistry()
    with console.status("[bold green]Processing batch results into videos..."):
        process_batch_results(results, analysis_list, configs_list, cost_tracker=cost_tracker, render_registry=render_registry)
    session = cost_tracker.get_session_summary()
    console.print(Panel(
        f"[green]Tracks:[/green] {len(analysis_list)}\n[green]Images:[/green] {success}\n[green]Cost:[/green] ${session['session_cost']:.2f} (batch pricing)\n[green]Output:[/green] {output_base}",
        title="[bold green]Batch Processing Complete[/bold green]",
    ))


@batch.command("list")
@click.option("--limit", "-n", type=int, default=20, help="Number of batches to show")
@click.pass_context
def batch_list(ctx, limit):
    """List recent OpenAI batches."""
    with console.status("[bold green]Fetching batches..."):
        batches = list_batches(limit=limit)
    if not batches:
        console.print("[dim]No batches found.[/dim]")
        return
    table = Table(title="OpenAI Batches")
    table.add_column("Batch ID", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Progress", justify="right")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Created", style="dim")
    for b in batches:
        sv = b["status"]
        color = {"completed": "green", "failed": "red", "in_progress": "yellow", "validating": "cyan", "expired": "red", "cancelled": "dim"}.get(sv, "white")
        table.add_row(b["id"], f"[{color}]{sv}[/{color}]", f"{b['completed']}/{b['total']}", str(b["failed"]) if b["failed"] else "", str(b.get("created_at", "")))
    console.print(table)


@main.command()
def styles():
    """List available visual style presets."""
    style_names = _list_styles()

    if not style_names:
        console.print("[red]No styles found[/red]")
        return

    table = Table(title="Available Visual Styles")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Colors", style="magenta")

    for name in style_names:
        config = _load_style(name)
        desc = config.get("description", "")
        colors_cfg = config.get("colors", {})
        color_str = " ".join(f"[{c}]██[/{c}]" if c.startswith("#") else c
                             for c in colors_cfg.values())
        table.add_row(name, desc, color_str)

    console.print(table)


@main.command()
@click.argument("output_dir", type=click.Path(exists=True))
@click.option("--layer", "-l", type=str, default=None, help="Filter by layer (drops/buildups/breakdowns/ambient)")
@click.pass_context
def preview(ctx, output_dir, layer):
    """Preview generated clips — opens in system video player."""
    import subprocess as sp

    out = Path(output_dir)

    # Look for resolume deck first, then loops, then clips
    resolume_dir = out / "resolume"
    if resolume_dir.exists():
        clips_to_play = []
        for layer_dir in sorted(resolume_dir.iterdir()):
            if not layer_dir.is_dir():
                continue
            if layer and layer.lower() not in layer_dir.name.lower():
                continue
            for clip in sorted(layer_dir.glob("*.mp4")):
                clips_to_play.append(clip)
    else:
        loops_dir = out / "loops"
        clips_dir = out / "clips"
        source = loops_dir if loops_dir.exists() else clips_dir if clips_dir.exists() else out
        clips_to_play = sorted(source.glob("*.mp4"))

    if not clips_to_play:
        console.print(f"[red]No clips found in {output_dir}[/red]")
        return

    console.print(f"[cyan]Opening {len(clips_to_play)} clips...[/cyan]")
    for clip in clips_to_play:
        console.print(f"  {clip.name}")

    # Open all clips (macOS: open with default player)
    for clip in clips_to_play:
        sp.run(["open", str(clip)], check=False)


@main.command()
@click.argument("output_dir", type=click.Path(exists=True))
@click.pass_context
def info(ctx, output_dir):
    """Show info about generated output for a track."""
    import json as json_mod

    out = Path(output_dir)
    meta_path = out / "metadata.json"
    analysis_path = out / "analysis.json"

    if not meta_path.exists():
        console.print(f"[red]No metadata.json found in {output_dir}[/red]")
        return

    meta = json_mod.loads(meta_path.read_text())

    table = Table(title=f"Output: {meta.get('track', 'Unknown')}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("BPM", f"{meta.get('bpm', 0):.1f}")
    table.add_row("Duration", f"{meta.get('duration', 0):.1f}s")
    table.add_row("Clips", str(len(meta.get('clips', []))))
    table.add_row("Loops", str(len(meta.get('loops', []))))

    console.print(table)

    # Show loops by type
    loops = meta.get("loops", [])
    if loops:
        loop_table = Table(title="Loops")
        loop_table.add_column("File", style="white")
        loop_table.add_column("Type", style="cyan")
        loop_table.add_column("Beats", style="yellow")
        loop_table.add_column("Duration", style="green")

        for loop in loops:
            loop_table.add_row(
                Path(loop.get("file", "")).name,
                loop.get("label", ""),
                str(loop.get("beats", 0)),
                f"{loop.get('duration', 0):.1f}s",
            )
        console.print(loop_table)

    # Resolume deck info
    deck_path = out / "resolume" / "deck_info.json"
    if deck_path.exists():
        deck = json_mod.loads(deck_path.read_text())
        console.print(f"\n[bold]Resolume Deck:[/bold] {deck.get('total_clips', 0)} clips")
        for layer_info in deck.get("layers", {}).values():
            if layer_info.get("clips"):
                console.print(f"  {layer_info['name']}: {len(layer_info['clips'])} clips")


@main.group()
@click.pass_context
def dashboard(ctx):
    """Cost tracking, render stats, and reporting."""
    pass


@dashboard.command("costs")
@click.option("--days", type=int, default=30, help="Number of days for daily breakdown")
@click.pass_context
def dashboard_costs(ctx, days):
    """Show cost summary — total spend, breakdowns by track/style/day."""
    from datetime import datetime, timedelta
    from .tracking import CostTracker

    budget = ctx.obj.get("budget")
    tracker = CostTracker(budget_limit=budget)

    total = tracker.get_total_cost()
    total_calls = tracker.get_total_calls()
    cache_rate = tracker.get_cache_hit_rate()

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    cost_today = tracker.get_total_cost(since=today_start)
    cost_week = tracker.get_total_cost(since=week_start)
    cost_month = tracker.get_total_cost(since=month_start)

    # Summary panel
    budget_line = ""
    if budget:
        pct = (total / budget * 100) if budget > 0 else 0
        color = "green" if pct < 60 else "yellow" if pct < 80 else "red"
        budget_line = f"\n[{color}]Budget:[/{color}] ${total:.2f} / ${budget:.2f} ({pct:.0f}%)"

    console.print(Panel(
        f"[green]Total Spend:[/green] ${total:.4f}\n"
        f"[green]Today:[/green] ${cost_today:.4f}\n"
        f"[green]This Week:[/green] ${cost_week:.4f}\n"
        f"[green]This Month:[/green] ${cost_month:.4f}\n"
        f"[green]API Calls:[/green] {total_calls}\n"
        f"[green]Cache Hit Rate:[/green] {cache_rate:.1%}"
        + budget_line,
        title="[bold cyan]Cost Summary[/bold cyan]",
    ))

    # By track
    by_track = tracker.get_cost_by_track()
    if by_track:
        table = Table(title="Cost by Track")
        table.add_column("Track", style="cyan")
        table.add_column("API Calls", style="white", justify="right")
        table.add_column("Cache Hits", style="dim", justify="right")
        table.add_column("Cost", style="green", justify="right")

        for row in by_track:
            table.add_row(
                row["track_name"] or "(unknown)",
                str(row["api_calls"]),
                str(row["cache_hits"]),
                f"${row['total_cost']:.4f}",
            )
        console.print(table)

    # By style
    by_style = tracker.get_cost_by_style()
    if by_style:
        table = Table(title="Cost by Style")
        table.add_column("Style", style="cyan")
        table.add_column("Calls", style="white", justify="right")
        table.add_column("Cost", style="green", justify="right")

        for row in by_style:
            table.add_row(
                row["style"] or "(unknown)",
                str(row["calls"]),
                f"${row['total_cost']:.4f}",
            )
        console.print(table)

    # By day
    by_day = tracker.get_cost_by_day(days=days)
    if by_day:
        table = Table(title=f"Cost by Day (last {days} days)")
        table.add_column("Day", style="cyan")
        table.add_column("Calls", style="white", justify="right")
        table.add_column("Cost", style="green", justify="right")

        for row in by_day:
            table.add_row(
                row["day"],
                str(row["calls"]),
                f"${row['cost']:.4f}",
            )
        console.print(table)

    if not by_track and not by_style and not by_day:
        console.print("[dim]No cost data recorded yet.[/dim]")


@dashboard.command("renders")
@click.option("--limit", "-n", type=int, default=20, help="Number of recent renders to show")
@click.pass_context
def dashboard_renders(ctx, limit):
    """Show render status — totals, unique tracks, output size, recent renders."""
    from .tracking import RenderRegistry

    registry = RenderRegistry()
    stats = registry.get_render_stats()

    # Status panel
    total = stats["total_renders"]
    completed = stats["completed"]
    failed = stats["failed"]
    in_progress = stats["in_progress"]
    size_mb = stats["total_output_size_mb"]
    unique = stats["unique_tracks"]
    cache_renders = stats["cache_hit_renders"]
    cache_rate = (cache_renders / total * 100) if total > 0 else 0

    console.print(Panel(
        f"[green]Total Renders:[/green] {total}\n"
        f"[green]Completed:[/green] {completed}\n"
        f"[red]Failed:[/red] {failed}\n"
        f"[yellow]In Progress:[/yellow] {in_progress}\n"
        f"[green]Unique Tracks:[/green] {unique}\n"
        f"[green]Total Output:[/green] {size_mb:.1f} MB\n"
        f"[green]Cache Hit Rate:[/green] {cache_rate:.1f}%",
        title="[bold cyan]Render Stats[/bold cyan]",
    ))

    # Recent renders
    all_renders = registry.get_all_renders()
    recent = all_renders[:limit]

    if recent:
        table = Table(title=f"Recent Renders (last {len(recent)})")
        table.add_column("Track", style="cyan", max_width=30)
        table.add_column("Style", style="white")
        table.add_column("Phrase", style="dim", justify="right")
        table.add_column("Status", justify="center")
        table.add_column("Cost", style="green", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Started", style="dim")

        for r in recent:
            status = r["status"]
            if status == "completed":
                status_str = "[green]completed[/green]"
            elif status == "failed":
                status_str = "[red]failed[/red]"
            elif status == "in_progress":
                status_str = "[yellow]in_progress[/yellow]"
            else:
                status_str = f"[dim]{status}[/dim]"

            size_str = ""
            if r.get("output_size") and r["output_size"] > 0:
                size_kb = r["output_size"] / 1024
                size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"

            started = r.get("started_at", "")
            if started and len(started) > 16:
                started = started[:16]

            table.add_row(
                r.get("track_name", ""),
                r.get("style", ""),
                str(r.get("phrase_idx", "")),
                status_str,
                f"${r.get('cost_usd', 0):.4f}",
                size_str,
                started,
            )
        console.print(table)
    else:
        console.print("[dim]No renders recorded yet.[/dim]")

    # Failed renders detail
    failed_renders = [r for r in all_renders if r["status"] == "failed"]
    if failed_renders:
        console.print(f"\n[red bold]Failed Renders ({len(failed_renders)}):[/red bold]")
        for r in failed_renders[:5]:
            console.print(
                f"  [red]x[/red] {r.get('track_name', '')} "
                f"phrase {r.get('phrase_idx', '?')}: "
                f"{r.get('error_message', 'unknown error')}"
            )


@dashboard.command("report")
@click.argument("output", type=click.Path(), default="rsv_report.json")
@click.pass_context
def dashboard_report(ctx, output):
    """Export full JSON report (costs + renders) to a file."""
    from .tracking import CostTracker, RenderRegistry

    budget = ctx.obj.get("budget")
    tracker = CostTracker(budget_limit=budget)
    registry = RenderRegistry()

    cost_report = tracker.export_json()
    render_stats = registry.get_render_stats()
    all_renders = registry.get_all_renders()
    track_renders = registry.get_track_renders()

    report = {
        "costs": cost_report,
        "renders": {
            "stats": render_stats,
            "all_renders": all_renders,
            "track_renders": track_renders,
        },
    }

    out_path = Path(output)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    console.print(f"[green]Report exported to:[/green] {out_path.resolve()}")


@dashboard.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def dashboard_reset(ctx, yes):
    """Reset all cost and render tracking data."""
    from .tracking.costs import DEFAULT_DB_PATH as COSTS_DB
    from .tracking.registry import DEFAULT_DB_PATH as REGISTRY_DB

    if not yes:
        click.confirm(
            "This will permanently delete all cost and render tracking data. Continue?",
            abort=True,
        )

    deleted = []
    for db_path, label in [(COSTS_DB, "costs"), (REGISTRY_DB, "renders")]:
        if db_path.exists():
            db_path.unlink()
            deleted.append(label)
            console.print(f"[yellow]Deleted:[/yellow] {db_path}")
        else:
            console.print(f"[dim]Not found (already clean):[/dim] {db_path}")

    if deleted:
        console.print(f"[green]Reset complete.[/green] Cleared: {', '.join(deleted)}")
    else:
        console.print("[dim]Nothing to reset.[/dim]")


@dashboard.command("logs")
@click.argument("run_id", required=False)
@click.option("--limit", "-n", type=int, default=10, help="Number of recent runs to show")
@click.pass_context
def dashboard_logs(ctx, run_id, limit):
    """Show recent run logs, or details for a specific run."""
    run_logger = RunLogger()

    if run_id:
        # Detailed view of a specific run
        events = run_logger.get_run_log(run_id)
        if not events:
            console.print(f"[red]No log found for run: {run_id}[/red]")
            return

        start = events[0] if events else {}
        console.print(Panel(
            f"[bold]Log ID:[/bold] {run_id}\n"
            f"[bold]Command:[/bold] {start.get('command', '')}\n"
            f"[bold]Started:[/bold] {start.get('timestamp', '')}\n"
            f"[bold]Args:[/bold] {json.dumps(start.get('args', {}), indent=2)}",
            title="[bold cyan]Run Details[/bold cyan]",
        ))

        # Show track events
        track_events = [e for e in events if e.get("type") == "track"]
        if track_events:
            table = Table(title="Tracks")
            table.add_column("Track", style="cyan", max_width=40)
            table.add_column("Status", justify="center")
            table.add_column("BPM", style="green", justify="right")
            table.add_column("Phrases", justify="right")
            table.add_column("Clips", justify="right")
            table.add_column("Cost", style="green", justify="right")
            table.add_column("Error", style="red", max_width=30)

            for t in track_events:
                status = t.get("status", "")
                status_str = f"[green]{status}[/green]" if status == "completed" else f"[red]{status}[/red]"
                table.add_row(
                    t.get("track", ""),
                    status_str,
                    f"{t.get('bpm', 0):.1f}" if t.get("bpm") else "-",
                    str(t.get("phrases", 0)),
                    str(t.get("clips", 0)),
                    f"${t.get('cost', 0):.4f}",
                    t.get("error", "")[:30] if t.get("error") else "",
                )
            console.print(table)

        # Show other events
        other_events = [e for e in events if e.get("type") == "event"]
        if other_events:
            console.print("\n[bold]Events:[/bold]")
            for e in other_events:
                level = e.get("level", "info")
                color = {"error": "red", "warning": "yellow", "debug": "dim"}.get(level, "white")
                console.print(f"  [{color}][{level}][/{color}] {e.get('message', '')}")

        # Show summary if run ended
        end_events = [e for e in events if e.get("type") == "run_end"]
        if end_events:
            summary = end_events[-1].get("summary", {})
            console.print(Panel(
                "\n".join(f"[green]{k}:[/green] {v}" for k, v in summary.items()),
                title="[bold green]Run Summary[/bold green]",
            ))
    else:
        # List recent runs
        runs = run_logger.get_recent_runs(limit=limit)
        if not runs:
            console.print("[dim]No run logs found.[/dim]")
            return

        table = Table(title=f"Recent Runs (last {len(runs)})")
        table.add_column("Log ID", style="cyan")
        table.add_column("Command", style="white")
        table.add_column("Started", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Tracks", justify="right")
        table.add_column("Cost", style="green", justify="right")

        for r in runs:
            status = r.get("status", "")
            status_str = f"[green]{status}[/green]" if status == "completed" else f"[yellow]{status}[/yellow]"
            started = r.get("started_at", "")
            if started and len(started) > 19:
                started = started[:19]
            table.add_row(
                r.get("log_id", ""),
                r.get("command", ""),
                started,
                status_str,
                str(r.get("tracks", 0)),
                f"${r.get('total_cost', 0):.4f}",
            )
        console.print(table)
        console.print("\n[dim]View details: rsv dashboard logs <log_id>[/dim]")


@main.command()
@click.argument("directory", type=click.Path(exists=True))
@click.option("--style", "-s", type=str, default="auto", help="Visual style preset (default: auto — use genre detection)")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--output-dir", "-o", type=str, default="output", help="Output directory")
@click.option("--poll-interval", type=int, default=10, help="Polling interval in seconds")
@click.pass_context
def watch(ctx, directory, style, quality, output_dir, poll_interval):
    """Watch a directory for new music files and auto-generate visuals."""
    from .watcher import run_watcher

    run_watcher(
        directory=directory,
        style=style,
        quality=quality,
        output_dir=output_dir,
        poll_interval=poll_interval,
    )


@main.command()
@click.argument("output_dir", type=click.Path(exists=True))
@click.option("--thumb-size", type=int, default=200, help="Thumbnail size in pixels")
@click.pass_context
def thumbnails(ctx, output_dir, thumb_size):
    """Generate a thumbnail contact sheet from existing output."""
    from .composer.thumbnails import create_thumbnail_grid

    out = Path(output_dir)
    meta_path = out / "metadata.json"
    analysis_path = out / "analysis.json"

    if not meta_path.exists():
        console.print(f"[red]No metadata.json found in {output_dir}[/red]")
        return

    meta = json.loads(meta_path.read_text())
    analysis = json.loads(analysis_path.read_text()) if analysis_path.exists() else {}

    clips = meta.get("clips", [])
    if not clips:
        console.print(f"[red]No clips found in metadata[/red]")
        return

    track_name = _sanitize_name(meta.get("track", "output"))
    thumbnail_path = out / f"{track_name}_thumbnails.png"

    config = {"thumb_size": thumb_size}
    with console.status("[bold green]Building contact sheet..."):
        result = create_thumbnail_grid(clips, analysis, thumbnail_path, config)

    console.print(f"[green]Thumbnail grid created:[/green] {result}")


@main.command("export-composition")
@click.argument("output_dir", type=click.Path(exists=True))
@click.option("--output-file", "-o", type=str, default=None,
              help="Output .avc filename (default: <track_name>.avc)")
@click.option("--multi-track", is_flag=True, default=False,
              help="Combine all tracks in output_dir into a multi-track composition")
@click.pass_context
def export_composition(ctx, output_dir, output_file, multi_track):
    """Export a Resolume Arena .avc composition file from generated output."""
    from .resolume.composition import create_composition, create_multi_track_composition

    out = Path(output_dir)

    if multi_track:
        # Collect all track metadata from subdirectories
        tracks = []
        for sub in sorted(out.iterdir()):
            meta_path = sub / "metadata.json"
            if sub.is_dir() and meta_path.exists():
                meta = json.loads(meta_path.read_text())
                tracks.append(meta)

        if not tracks:
            console.print(f"[red]No track metadata found in subdirectories of {output_dir}[/red]")
            return

        avc_name = output_file or "multi_track_set.avc"
        avc_path = out / avc_name

        console.print(f"[cyan]Creating multi-track composition ({len(tracks)} tracks)...[/cyan]")
        result = create_multi_track_composition(tracks, avc_path)
        console.print(f"[green]Composition exported:[/green] {result}")

    else:
        # Single track
        meta_path = out / "metadata.json"
        if not meta_path.exists():
            console.print(f"[red]No metadata.json found in {output_dir}[/red]")
            return

        meta = json.loads(meta_path.read_text())
        track_name = _sanitize_name(meta.get("track", "composition"))
        avc_name = output_file or f"{track_name}.avc"
        avc_path = out / avc_name

        console.print(f"[cyan]Creating composition for: {meta.get('track', 'Unknown')}...[/cyan]")
        result = create_composition(meta, avc_path, clip_base_path=out)
        console.print(f"[green]Composition exported:[/green] {result}")


@main.command()
@click.argument("output_dir", type=click.Path(exists=True))
@click.option("--width", type=int, default=1920, help="Expected video width")
@click.option("--height", type=int, default=1080, help="Expected video height")
@click.option("--codec", type=str, default="h264", help="Expected video codec")
@click.pass_context
def validate(ctx, output_dir, width, height, codec):
    """Validate generated video files in an output directory."""
    from .validation import validate_directory

    console.print(f"\n[bold cyan]Validating:[/bold cyan] {output_dir}\n")

    summary = validate_directory(
        output_dir,
        expected_width=width,
        expected_height=height,
        expected_codec=codec,
    )

    total = summary["total"]
    valid = summary["valid"]
    invalid = summary["invalid"]
    size_mb = summary["total_size_bytes"] / (1024 * 1024)

    if total == 0:
        console.print("[yellow]No .mp4 files found in directory.[/yellow]")
        return

    console.print(Panel(
        f"[green]Total files:[/green] {total}\n"
        f"[green]Valid:[/green] {valid}\n"
        f"[red]Invalid:[/red] {invalid}\n"
        f"[green]Total size:[/green] {size_mb:.1f} MB",
        title="[bold cyan]Validation Summary[/bold cyan]",
    ))

    if summary["invalid_files"]:
        console.print("\n[bold red]Invalid Files:[/bold red]")
        for entry in summary["invalid_files"]:
            console.print(f"  [red]x[/red] {entry['path']}")
            for err in entry["errors"]:
                console.print(f"      {err}")


# ──────────────────────────────────────────────────────────────────────
# Lexicon DJ integration commands
# ──────────────────────────────────────────────────────────────────────

@main.group()
@click.pass_context
def lexicon(ctx):
    """Lexicon DJ integration — generate visuals from your DJ library."""
    pass


@lexicon.command("connect")
@click.option("--host", type=str, default=None, help="Lexicon host IP")
@click.option("--port", type=int, default=None, help="Lexicon API port")
@click.pass_context
def lexicon_connect(ctx, host, port):
    """Test Lexicon API connection."""
    from .lexicon import LexiconClient, DEFAULT_HOST, DEFAULT_PORT

    h = host or DEFAULT_HOST
    p = port or DEFAULT_PORT
    console.print(f"\n[bold cyan]Testing Lexicon API:[/bold cyan] http://{h}:{p}/v1/\n")

    client = LexiconClient(host=h, port=p)
    result = client.test_connection()

    if result.get("connected"):
        console.print(f"  [green]Connected[/green] — {result['total_tracks']} tracks in library")
    else:
        console.print(f"  [red]Connection failed:[/red] {result.get('error', 'unknown')}")
        console.print("  Make sure Lexicon is running with API enabled in Settings > Integrations")


@lexicon.command("library")
@click.option("--host", type=str, default=None, help="Lexicon host IP")
@click.option("--port", type=int, default=None, help="Lexicon API port")
@click.pass_context
def lexicon_library(ctx, host, port):
    """Show library stats and genres."""
    from .lexicon import LexiconClient, DEFAULT_HOST, DEFAULT_PORT

    h = host or DEFAULT_HOST
    p = port or DEFAULT_PORT
    client = LexiconClient(host=h, port=p)

    console.print(f"\n[bold cyan]Lexicon Library Stats[/bold cyan]\n")

    with console.status("[bold green]Fetching library..."):
        tracks = client.get_all_tracks()

    if not tracks:
        console.print("[red]No tracks found. Is Lexicon running?[/red]")
        return

    # Basic stats
    console.print(f"  [bold]Total tracks:[/bold] {len(tracks)}")

    # Genre breakdown
    genres = {}
    bpms = []
    artists = set()
    for t in tracks:
        genre = t.get("genre") or "Unknown"
        genres[genre] = genres.get(genre, 0) + 1
        if t.get("bpm"):
            bpms.append(t["bpm"])
        if t.get("artist"):
            artists.add(t["artist"])

    console.print(f"  [bold]Artists:[/bold] {len(artists)}")
    if bpms:
        console.print(f"  [bold]BPM range:[/bold] {min(bpms):.0f} - {max(bpms):.0f}")

    # Genre table
    genre_table = Table(title="Genres")
    genre_table.add_column("Genre", style="cyan")
    genre_table.add_column("Tracks", style="green", justify="right")
    genre_table.add_column("", style="dim")

    for genre, count in sorted(genres.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 40)
        genre_table.add_row(genre, str(count), bar)

    console.print(genre_table)

    # Playlists
    try:
        playlists = client.get_playlists()
        if playlists:
            console.print(f"\n  [bold]Playlists:[/bold] {len(playlists)}")
            for pl in playlists:
                console.print(f"    - {pl.get('name', 'Unnamed')} ({pl.get('trackCount', '?')} tracks)")
    except Exception:
        pass


@lexicon.command("generate")
@click.argument("track_title")
@click.option("--brand", type=str, default=None, help="Brand guide name (e.g. will_see)")
@click.option("--host", type=str, default=None, help="Lexicon host IP")
@click.option("--port", type=int, default=None, help="Lexicon API port")
@click.option("--output-dir", "-o", type=str, default="output/lexicon", help="Output directory")
@click.option("--style", "-s", type=str, default=None, help="Style override to layer on brand prompts")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--dry-run", is_flag=True, default=False, help="Plan only, no generation")
@click.pass_context
def lexicon_generate(ctx, track_title, brand, host, port, output_dir, style,
                     quality, dry_run):
    """Generate video for one track from Lexicon library.

    Uses the full-song pipeline: Flux LoRA keyframes -> Kling i2v animation
    -> DXV encoding -> NAS push.

    With --brand, uses brand-specific prompts and LoRA weights.
    Without --brand, falls back to the legacy pipeline.

    Examples:

        rsv lexicon generate "Nan Slapper (Original Mix)" --brand will_see

        rsv lexicon generate "Track Name" --brand will_see --style tunnel --dry-run
    """
    from .lexicon import LexiconClient, DEFAULT_HOST, DEFAULT_PORT

    h = host or DEFAULT_HOST
    p = port or DEFAULT_PORT
    client = LexiconClient(host=h, port=p)

    console.print(f"\n[bold cyan]Searching:[/bold cyan] {track_title}\n")

    with console.status("[bold green]Searching Lexicon library..."):
        matches = client.search_tracks(track_title)

    if not matches:
        console.print(f"[red]No tracks found matching '{track_title}'[/red]")
        return

    if len(matches) > 1:
        console.print(f"Found {len(matches)} matches, using first:")
        for m in matches[:5]:
            console.print(f"  - {m.get('artist', '?')} — {m.get('title', '?')} ({m.get('bpm', '?')} BPM)")

    track = matches[0]
    title = track.get("title", "Unknown")
    artist = track.get("artist", "Unknown")
    console.print(f"\n[bold]Track:[/bold] {artist} — {title}")
    console.print(f"[bold]BPM:[/bold] {track.get('bpm', '?')} | "
                  f"[bold]Key:[/bold] {track.get('key', '?')} | "
                  f"[bold]Genre:[/bold] {track.get('genre', '?')}")

    # Brand pipeline (new) vs legacy pipeline
    if brand:
        from .pipeline import FullSongPipeline, _load_brand_config, _load_lora_url
        import subprocess

        brand_config = _load_brand_config(brand)
        lora_url = _load_lora_url(brand)
        brand_config["lora_weights_url"] = lora_url

        console.print(f"[bold]Brand:[/bold] {brand_config.get('name', brand)}")
        console.print(f"[bold]LoRA:[/bold] {'loaded' if lora_url else 'none'}")

        # Load API keys from 1Password
        fal_key = os.environ.get("FAL_KEY", "")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not fal_key:
            try:
                result = subprocess.run(
                    ["op", "read", "op://OpenClaw/Fal.ai API/credential"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    fal_key = result.stdout.strip()
            except Exception:
                pass
        if not openai_key:
            try:
                result = subprocess.run(
                    ["op", "read", "op://OpenClaw/OpenClaw Secret - OPENAI_API_KEY/password"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    openai_key = result.stdout.strip()
            except Exception:
                pass

        if not fal_key:
            console.print("[red]FAL_KEY not found. Set env var or install 1Password CLI.[/red]")
            return

        pipeline = FullSongPipeline(
            brand_config=brand_config,
            fal_key=fal_key,
            openai_key=openai_key,
        )

        out = Path(output_dir)

        if dry_run:
            console.print(f"\n[bold yellow]Dry run — planning segments...[/bold yellow]")
        else:
            console.print(f"\n[bold yellow]Generating video via brand pipeline...[/bold yellow]")

        try:
            result = pipeline.generate_for_track(
                track=track,
                output_dir=out,
                style_override=style or "",
                quality=quality,
                dry_run=dry_run,
            )

            if dry_run:
                segments = result.get("segments", [])
                console.print(Panel(
                    f"[green]Track:[/green] {artist} — {title}\n"
                    f"[green]BPM:[/green] {result.get('bpm', '?')}\n"
                    f"[green]Genre:[/green] {result.get('genre', '?')}\n"
                    f"[green]Duration:[/green] {result.get('duration', 0):.1f}s\n"
                    f"[green]Segments:[/green] {len(segments)}\n"
                    f"[green]Structure:[/green] {' -> '.join(s['label'] for s in segments)}",
                    title="[bold yellow]Dry Run — Segment Plan[/bold yellow]",
                ))
                for i, seg in enumerate(segments):
                    console.print(
                        f"  {i+1:2d}. [{seg['label']:>10s}] "
                        f"{seg['start']:6.1f}s - {seg['end']:6.1f}s "
                        f"({seg['duration']:.1f}s)"
                    )
            elif result.get("skipped"):
                console.print(Panel(
                    f"[yellow]Track already exists on NAS[/yellow]\n"
                    f"[green]NAS path:[/green] {result.get('nas_path', '?')}",
                    title="[bold yellow]Skipped[/bold yellow]",
                ))
            else:
                console.print(Panel(
                    f"[green]Track:[/green] {artist} — {title}\n"
                    f"[green]Brand:[/green] {result.get('brand', brand)}\n"
                    f"[green]Segments:[/green] {result.get('segments', '?')}\n"
                    f"[green]NAS path:[/green] {result.get('nas_path', '?')}\n"
                    f"[green]Resolume path:[/green] {result.get('local_vj_path', '?')}",
                    title="[bold green]Video Generated[/bold green]",
                ))
        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")
            logger.exception("Brand pipeline generation failed")
    else:
        # Legacy pipeline (no brand)
        from .lexicon import VideoGenerationConfig, generate_video_for_track

        config = VideoGenerationConfig(
            style_name=style or "abstract",
            backend="openai",
            quality=quality,
        )

        out = Path(output_dir)
        console.print(f"\n[bold yellow]Generating video (legacy pipeline)...[/bold yellow]")

        try:
            nas_path = generate_video_for_track(track, out, config)
            console.print(Panel(
                f"[green]Track:[/green] {artist} — {title}\n"
                f"[green]NAS path:[/green] {nas_path}\n"
                f"[green]Output:[/green] {out}",
                title="[bold green]Video Generated[/bold green]",
            ))
        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")
            logger.exception("Video generation failed")


@lexicon.command("show")
@click.option("--brand", type=str, default=None, help="Brand guide name (e.g. will_see)")
@click.option("--host", type=str, default=None, help="Lexicon host IP")
@click.option("--port", type=int, default=None, help="Lexicon API port")
@click.option("--output-dir", "-o", type=str, default="output/lexicon", help="Output directory")
@click.option("--style", "-s", type=str, default=None, help="Style override to layer on brand prompts")
@click.option("--quality", "-q", type=click.Choice(["draft", "standard", "high"]), default="high")
@click.option("--show-name", type=str, default="Will See", help="Show composition name")
@click.option("--limit", "-n", type=int, default=None, help="Limit number of tracks (for testing)")
@click.pass_context
def lexicon_show(ctx, brand, host, port, output_dir, style, quality,
                 show_name, limit):
    """Build "Will See" .avc composition from all generated videos.

    With --brand: generates videos for all library tracks using the brand
    pipeline (Flux LoRA + Kling), then builds the Resolume composition.

    Without --brand: builds composition from already-generated videos in output-dir.

    Examples:

        rsv lexicon show --brand will_see

        rsv lexicon show --brand will_see --limit 5
    """
    from .lexicon import LexiconClient, DEFAULT_HOST, DEFAULT_PORT
    from .resolume.show import create_denon_show_composition, build_denon_show_from_output_dir

    h = host or DEFAULT_HOST
    p = port or DEFAULT_PORT
    client = LexiconClient(host=h, port=p)

    # Test connection
    conn = client.test_connection()
    if not conn.get("connected"):
        console.print(f"[red]Cannot connect to Lexicon: {conn.get('error')}[/red]")
        return

    total = conn["total_tracks"]
    effective = min(total, limit) if limit else total
    out = Path(output_dir)

    if brand:
        from .pipeline import FullSongPipeline, _load_brand_config, _load_lora_url
        import subprocess

        brand_config = _load_brand_config(brand)
        lora_url = _load_lora_url(brand)
        brand_config["lora_weights_url"] = lora_url

        console.print(f"\n[bold cyan]Generating show:[/bold cyan] {show_name}")
        console.print(f"  Brand: {brand_config.get('name', brand)}")
        console.print(f"  Tracks: {effective}" + (f" (limited from {total})" if limit else ""))
        console.print(f"  Quality: {quality}")

        # Load API keys
        fal_key = os.environ.get("FAL_KEY", "")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not fal_key:
            try:
                result = subprocess.run(
                    ["op", "read", "op://OpenClaw/Fal.ai API/credential"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    fal_key = result.stdout.strip()
            except Exception:
                pass
        if not openai_key:
            try:
                result = subprocess.run(
                    ["op", "read", "op://OpenClaw/OpenClaw Secret - OPENAI_API_KEY/password"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    openai_key = result.stdout.strip()
            except Exception:
                pass

        if not fal_key:
            console.print("[red]FAL_KEY not found. Set env var or install 1Password CLI.[/red]")
            return

        pipeline = FullSongPipeline(
            brand_config=brand_config,
            fal_key=fal_key,
            openai_key=openai_key,
        )

        # Pull tracks
        with console.status("[bold green]Fetching library..."):
            if limit:
                tracks = client.get_tracks(limit=limit)
            else:
                tracks = client.get_all_tracks()

        console.print(f"  Found {len(tracks)} tracks\n")

        # Generate video for each track
        generated = []
        for i, track in enumerate(tracks):
            t_title = track.get("title", "Unknown")
            t_artist = track.get("artist", "Unknown")
            console.print(f"[{i+1}/{len(tracks)}] {t_artist} — {t_title}")

            try:
                meta = pipeline.generate_for_track(
                    track=track,
                    output_dir=out,
                    style_override=style or "",
                    quality=quality,
                )
                generated.append(meta)
                if meta.get("skipped"):
                    console.print(f"  [dim]Skipped (exists on NAS)[/dim]")
                else:
                    console.print(f"  [green]Done[/green] -> {meta.get('nas_path', '?')}")
            except Exception as e:
                console.print(f"  [red]Failed: {e}[/red]")
                logger.error(f"Failed to generate video for {t_title}: {e}")

        if not generated:
            console.print("[red]No videos generated.[/red]")
            return

        # Build .avc composition
        avc_path = out / f"{show_name}.avc"
        create_denon_show_composition(generated, avc_path, show_name=show_name)

        # Push composition to NAS
        from .lexicon import NAS_VJ_CONTENT_PREFIX, push_to_nas as _push_nas
        nas_avc = f"{NAS_VJ_CONTENT_PREFIX}{show_name}.avc"
        try:
            _push_nas(avc_path, nas_avc)
        except Exception as e:
            logger.warning(f"Failed to push .avc to NAS: {e}")

        console.print(Panel(
            f"[green]Show:[/green] {show_name}\n"
            f"[green]Brand:[/green] {brand_config.get('name', brand)}\n"
            f"[green]Tracks:[/green] {len(generated)}\n"
            f"[green]Composition:[/green] {avc_path}\n"
            f"[green]NAS:[/green] {nas_avc}",
            title="[bold green]Show Generated[/bold green]",
        ))
    else:
        # No brand: build composition from existing generated videos
        avc_path = out / f"{show_name}.avc"
        console.print(f"\n[bold cyan]Building composition:[/bold cyan] {show_name}")
        console.print(f"  Scanning: {out}")

        try:
            result = build_denon_show_from_output_dir(out, avc_path, show_name=show_name)
            console.print(Panel(
                f"[green]Composition:[/green] {result}\n"
                f"[green]Transport:[/green] Denon (auto-switch by track title)",
                title="[bold green]Composition Built[/bold green]",
            ))
        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")
            logger.exception("Composition build failed")


@lexicon.command("composition")
@click.option("--output-dir", "-o", type=str, default="output/lexicon", help="Output directory with generated videos")
@click.option("--show-name", type=str, default="Will See", help="Show composition name")
@click.pass_context
def lexicon_composition(ctx, output_dir, show_name):
    """Build .avc composition from already-generated videos."""
    from .resolume.show import build_denon_show_from_output_dir

    out = Path(output_dir)
    avc_path = out / f"{show_name}.avc"

    console.print(f"\n[bold cyan]Building composition:[/bold cyan] {show_name}")
    console.print(f"  Scanning: {out}")

    try:
        result = build_denon_show_from_output_dir(out, avc_path, show_name=show_name)
        console.print(Panel(
            f"[green]Composition:[/green] {result}\n"
            f"[green]Transport:[/green] Denon (auto-switch by track title)",
            title="[bold green]Composition Built[/bold green]",
        ))
    except Exception as e:
        console.print(f"[red]Failed: {e}[/red]")
        logger.exception("Composition build failed")


def _build_style_overrides(
    style_drop: str | None,
    style_buildup: str | None,
    style_breakdown: str | None,
    style_intro: str | None,
) -> dict | None:
    """
    Build a style_overrides dict from per-phrase-type CLI options.
    Returns None if no overrides specified.
    """
    mapping = {
        "drop": style_drop,
        "buildup": style_buildup,
        "breakdown": style_breakdown,
        "intro": style_intro,
    }

    overrides = {}
    for label, style_name in mapping.items():
        if style_name:
            overrides[label] = _load_style(style_name)

    return overrides if overrides else None


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use as directory/file name."""
    # Replace problematic characters
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(char, '_')
    return name.strip().strip('.')


@main.command()
@click.argument("directory", type=click.Path(exists=True))
@click.option("--recursive/--no-recursive", default=True, help="Scan subdirectories recursively")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table",
              help="Output format")
@click.option("--engine-db", type=click.Path(exists=True), default=None,
              help="Also read Engine DJ database")
@click.option("--rekordbox-xml", type=click.Path(exists=True), default=None,
              help="Also read Rekordbox XML export")
@click.pass_context
def scan(ctx, directory, recursive, output_format, engine_db, rekordbox_xml):
    """Scan a music directory and show track metadata."""
    console.print(f"\n[bold cyan]Scanning:[/bold cyan] {directory}")
    console.print(f"  Recursive: {recursive}\n")

    tracks = scan_library(directory, recursive=recursive)

    # Merge Engine DJ data if provided
    if engine_db:
        console.print(f"[bold cyan]Reading Engine DJ database:[/bold cyan] {engine_db}")
        engine_tracks = read_engine_db(engine_db)
        console.print(f"  Found {len(engine_tracks)} tracks in Engine DJ\n")
        tracks = _merge_metadata(tracks, engine_tracks)

    # Merge Rekordbox data if provided
    if rekordbox_xml:
        console.print(f"[bold cyan]Reading Rekordbox XML:[/bold cyan] {rekordbox_xml}")
        rb_tracks = read_rekordbox_xml(rekordbox_xml)
        console.print(f"  Found {len(rb_tracks)} tracks in Rekordbox\n")
        tracks = _merge_metadata(tracks, rb_tracks)

    if not tracks:
        console.print("[red]No music files found[/red]")
        return

    if output_format == "json":
        console.print(json.dumps(tracks, indent=2, default=str))
        return

    # Rich table output
    table = Table(title=f"Music Library ({len(tracks)} tracks)")
    table.add_column("Track", style="cyan", max_width=40)
    table.add_column("Artist", style="white", max_width=25)
    table.add_column("BPM", style="green", justify="right")
    table.add_column("Genre", style="magenta")
    table.add_column("Key", style="yellow")
    table.add_column("Format", style="dim")
    table.add_column("Size", style="dim", justify="right")

    for t in tracks:
        title = t.get("title") or Path(t["path"]).stem
        artist = t.get("artist") or ""
        bpm = f"{t['bpm']:.1f}" if t.get("bpm") else "-"
        genre = t.get("genre") or "-"
        key = t.get("key") or "-"
        fmt = t.get("format") or "-"
        size = _format_size(t.get("size", 0))
        table.add_row(title, artist, bpm, genre, key, fmt, size)

    console.print(table)


def _merge_metadata(file_tracks: list[dict], db_tracks: list[dict]) -> list[dict]:
    """Merge metadata from a DJ database into file-scanned tracks.

    DB data fills in missing fields (BPM, key, genre) but does not overwrite
    existing tag data.
    """
    # Build lookup by filename
    db_by_name = {}
    for t in db_tracks:
        name = Path(t.get("path", "")).stem.lower()
        if name:
            db_by_name[name] = t

    for track in file_tracks:
        name = Path(track["path"]).stem.lower()
        db_match = db_by_name.get(name)
        if db_match:
            for field in ("bpm", "key", "genre", "artist", "album"):
                if not track.get(field) and db_match.get(field):
                    track[field] = db_match[field]

    return file_tracks


def _format_size(size_bytes: int) -> str:
    """Format file size as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def _compute_audio_hash(file_path: str) -> str:
    """Compute a hash of the audio file for deterministic seeding."""
    import hashlib
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read first 64KB for speed — enough for unique identification
        h.update(f.read(65536))
    return h.hexdigest()


if __name__ == "__main__":
    main()
