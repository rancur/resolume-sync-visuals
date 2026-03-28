"""
CLI for resolume-sync-visuals.
Usage:
    rsv analyze <file>           — Analyze a track and print BPM/structure
    rsv generate <file>          — Generate visuals for a single track
    rsv bulk <directory>         — Process all tracks in a directory
    rsv styles                   — List available visual styles
    rsv watch <directory>        — Watch a directory for new music and auto-generate
"""
import json
import logging
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel

from .analyzer.audio import analyze_track
from .analyzer.genre import detect_genre_and_style
from .generator.engine import GenerationConfig, generate_visuals, resolve_phrase_style
from .composer.timeline import compose_timeline
from .composer.montage import create_montage
from .composer.thumbnails import create_thumbnail_grid
from .resolume.export import create_resolume_deck, generate_resolume_osc_script
from .tracking import CostTracker, RenderRegistry

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
@click.argument("file", type=click.Path(exists=True))
@click.option("--phrase-beats", "-p", type=int, default=None, help="Override phrase length in beats")
@click.option("--bpm", type=float, default=None, help="Override BPM (skip auto-detection)")
@click.option("--output", "-o", type=str, default=None, help="Output JSON path")
@click.pass_context
def analyze(ctx, file, phrase_beats, bpm, output):
    """Analyze a music track — BPM, beats, phrases, structure."""
    console.print(f"\n[bold cyan]Analyzing:[/bold cyan] {Path(file).name}\n")

    with console.status("[bold green]Analyzing audio..."):
        analysis = analyze_track(file, phrase_beats=phrase_beats, bpm_override=bpm)

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
@click.pass_context
def generate(ctx, file, style, backend, quality, output_dir, loop_beats,
             phrase_beats, bpm, width, height, fps, strobe, strobe_intensity, dry_run, montage,
             style_drop, style_buildup, style_breakdown, style_intro, thumbnails):
    """Generate beat-synced visuals for a single track."""
    file_path = Path(file)
    console.print(f"\n[bold cyan]Processing:[/bold cyan] {file_path.name}")

    # Resolve "auto" style via genre detection
    if style == "auto":
        with console.status("[bold green]Detecting genre..."):
            genre_hint, style = detect_genre_and_style(str(file_path))
        console.print(f"[magenta]Auto-detected genre:[/magenta] {genre_hint} -> style: {style}")

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
@click.pass_context
def bulk(ctx, directory, style, backend, quality, output_dir, loop_beats,
         max_concurrent, skip_existing):
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

    console.print(f"\n[bold cyan]Bulk Processing:[/bold cyan] {len(files)} tracks in {directory}")
    console.print(f"[bold]Style:[/bold] {style} | [bold]Backend:[/bold] {backend} | "
                  f"[bold]Quality:[/bold] {quality}\n")

    # List files
    for i, f in enumerate(files):
        console.print(f"  {i+1:3d}. {f.name}")

    console.print()

    if style != "auto":
        style_config = _load_style(style)
    else:
        style_config = None  # resolved per-track below
    output_base = Path(output_dir)

    completed = 0
    failed = 0

    for i, file_path in enumerate(files):
        track_name = _sanitize_name(file_path.stem)
        track_dir = output_base / track_name

        # Skip if already processed
        if skip_existing and (track_dir / "metadata.json").exists():
            console.print(f"[dim]Skipping (exists): {file_path.name}[/dim]")
            completed += 1
            continue

        console.print(f"\n[bold]{'='*60}[/bold]")
        console.print(f"[bold cyan]Track {i+1}/{len(files)}:[/bold cyan] {file_path.name}")

        try:
            # Resolve auto style per track
            track_style = style
            track_style_config = style_config
            if style == "auto":
                genre_hint, track_style = detect_genre_and_style(str(file_path))
                console.print(f"  [magenta]Auto-detected genre:[/magenta] {genre_hint} -> style: {track_style}")
                track_style_config = _load_style(track_style)

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
            console.print(f"  [green]✓ Complete — {len(clips)} clips[/green]")

        except Exception as e:
            failed += 1
            console.print(f"  [red]✗ Failed: {e}[/red]")
            logger.exception(f"Failed to process {file_path}")

    # Final summary
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(Panel(
        f"[green]Completed:[/green] {completed}/{len(files)}\n"
        f"[red]Failed:[/red] {failed}/{len(files)}\n"
        f"[blue]Output:[/blue] {output_base}",
        title="[bold]Bulk Processing Complete[/bold]",
    ))


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


if __name__ == "__main__":
    main()
