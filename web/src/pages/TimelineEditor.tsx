import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Scissors,
  Undo2,
  Save,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

interface Section {
  id: string;
  label: string;
  startTime: number;
  endTime: number;
  color: string;
}

const SECTION_COLORS: Record<string, string> = {
  intro: '#6366f1',
  buildup: '#f59e0b',
  drop: '#ef4444',
  breakdown: '#8b5cf6',
  outro: '#6b7280',
};

const SECTION_LABELS = ['intro', 'buildup', 'drop', 'breakdown', 'outro'];

// Demo waveform data
function generateDemoWaveform(duration: number, sampleRate: number = 100): number[] {
  const samples = Math.floor(duration * sampleRate);
  const data: number[] = [];
  for (let i = 0; i < samples; i++) {
    const t = i / sampleRate;
    const base = Math.sin(t * 2) * 0.3;
    const energy = Math.sin(t * 0.1) * 0.4 + 0.5;
    const noise = (Math.random() - 0.5) * 0.3;
    data.push(Math.max(0, Math.min(1, Math.abs(base + energy + noise))));
  }
  return data;
}

function generateDemoSections(duration: number): Section[] {
  const segDur = duration / 5;
  return SECTION_LABELS.map((label, i) => ({
    id: `s${i}`,
    label,
    startTime: i * segDur,
    endTime: (i + 1) * segDur,
    color: SECTION_COLORS[label] || '#6b7280',
  }));
}

export default function TimelineEditor() {
  const [duration] = useState(180); // 3 minutes demo
  const [sections, setSections] = useState<Section[]>(() => generateDemoSections(180));
  const [waveform] = useState<number[]>(() => generateDemoWaveform(180));
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState<{ sectionIdx: number; edge: 'start' | 'end' } | null>(null);
  const [history, setHistory] = useState<Section[][]>([]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const playIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Save history for undo
  const pushHistory = useCallback(() => {
    setHistory(h => [...h.slice(-20), sections.map(s => ({ ...s }))]);
  }, [sections]);

  const undo = useCallback(() => {
    setHistory(h => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setSections(prev);
      return h.slice(0, -1);
    });
  }, []);

  // Draw waveform
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * 2;
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);

    const w = rect.width;
    const h = rect.height;
    const totalWidth = w * zoom;

    ctx.clearRect(0, 0, w, h);

    // Draw section backgrounds
    for (const section of sections) {
      const x1 = (section.startTime / duration) * totalWidth;
      const x2 = (section.endTime / duration) * totalWidth;
      ctx.fillStyle = section.color + '20';
      ctx.fillRect(x1, 0, x2 - x1, h);
    }

    // Draw waveform
    const samplesPerPixel = waveform.length / totalWidth;
    ctx.beginPath();
    ctx.strokeStyle = '#4FC3F7';
    ctx.lineWidth = 1;
    for (let px = 0; px < totalWidth && px < w; px++) {
      const sampleIdx = Math.floor(px * samplesPerPixel);
      const val = waveform[sampleIdx] || 0;
      const y = h / 2 - val * (h / 2) * 0.8;
      if (px === 0) ctx.moveTo(px, y);
      else ctx.lineTo(px, y);
    }
    ctx.stroke();

    // Mirror waveform
    ctx.beginPath();
    ctx.strokeStyle = '#4FC3F780';
    for (let px = 0; px < totalWidth && px < w; px++) {
      const sampleIdx = Math.floor(px * samplesPerPixel);
      const val = waveform[sampleIdx] || 0;
      const y = h / 2 + val * (h / 2) * 0.8;
      if (px === 0) ctx.moveTo(px, y);
      else ctx.lineTo(px, y);
    }
    ctx.stroke();

    // Draw section boundaries
    for (const section of sections) {
      const x = (section.startTime / duration) * totalWidth;
      ctx.strokeStyle = section.color;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 2]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      ctx.setLineDash([]);

      // Label
      ctx.fillStyle = section.color;
      ctx.font = '10px system-ui';
      ctx.fillText(section.label.toUpperCase(), x + 4, 12);
    }

    // Beat markers (every beat assuming 128 BPM)
    const beatInterval = 60 / 128;
    ctx.strokeStyle = '#ffffff10';
    ctx.lineWidth = 0.5;
    for (let t = 0; t < duration; t += beatInterval) {
      const x = (t / duration) * totalWidth;
      if (x > w) break;
      ctx.beginPath();
      ctx.moveTo(x, h - 4);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // Playhead
    const phx = (currentTime / duration) * totalWidth;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(phx, 0);
    ctx.lineTo(phx, h);
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(phx - 4, 0);
    ctx.lineTo(phx + 4, 0);
    ctx.lineTo(phx, 6);
    ctx.fill();
  }, [waveform, sections, currentTime, duration, zoom]);

  // Playback
  useEffect(() => {
    if (playing) {
      playIntervalRef.current = setInterval(() => {
        setCurrentTime(t => {
          const next = t + 0.05;
          if (next >= duration) {
            setPlaying(false);
            return 0;
          }
          return next;
        });
      }, 50);
    } else {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    }
    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [playing, duration]);

  // Click to seek
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || dragging) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const t = (x / (rect.width * zoom)) * duration;
    setCurrentTime(Math.max(0, Math.min(duration, t)));
  };

  // Drag section boundary
  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const t = (x / (rect.width * zoom)) * duration;

    // Check if near a boundary
    const threshold = (duration / (rect.width * zoom)) * 8; // 8px threshold
    for (let i = 0; i < sections.length; i++) {
      if (Math.abs(sections[i].startTime - t) < threshold && i > 0) {
        pushHistory();
        setDragging({ sectionIdx: i, edge: 'start' });
        return;
      }
      if (Math.abs(sections[i].endTime - t) < threshold && i < sections.length - 1) {
        pushHistory();
        setDragging({ sectionIdx: i, edge: 'end' });
        return;
      }
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!dragging) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const t = Math.max(0, Math.min(duration, (x / (rect.width * zoom)) * duration));

    setSections(prev => {
      const next = prev.map(s => ({ ...s }));
      const { sectionIdx, edge } = dragging;
      if (edge === 'start') {
        const minT = sectionIdx > 0 ? next[sectionIdx - 1].startTime + 1 : 0;
        const maxT = next[sectionIdx].endTime - 1;
        const clamped = Math.max(minT, Math.min(maxT, t));
        next[sectionIdx].startTime = clamped;
        if (sectionIdx > 0) next[sectionIdx - 1].endTime = clamped;
      } else {
        const minT = next[sectionIdx].startTime + 1;
        const maxT = sectionIdx < next.length - 1 ? next[sectionIdx + 1].endTime - 1 : duration;
        const clamped = Math.max(minT, Math.min(maxT, t));
        next[sectionIdx].endTime = clamped;
        if (sectionIdx < next.length - 1) next[sectionIdx + 1].startTime = clamped;
      }
      return next;
    });
  };

  const handleCanvasMouseUp = () => {
    setDragging(null);
  };

  // Split section at current time
  const splitAtPlayhead = () => {
    const t = currentTime;
    const sIdx = sections.findIndex(s => t > s.startTime && t < s.endTime);
    if (sIdx < 0) return;
    pushHistory();
    const section = sections[sIdx];
    const newSections = [...sections];
    const newLabel = SECTION_LABELS[newSections.length % SECTION_LABELS.length];
    newSections.splice(sIdx, 1,
      { ...section, endTime: t },
      {
        id: `s${Date.now()}`,
        label: newLabel,
        startTime: t,
        endTime: section.endTime,
        color: SECTION_COLORS[newLabel] || '#6b7280',
      }
    );
    setSections(newSections);
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      switch (e.key) {
        case ' ':
          e.preventDefault();
          setPlaying(p => !p);
          break;
        case 'ArrowLeft':
          e.preventDefault();
          setCurrentTime(t => Math.max(0, t - 1));
          break;
        case 'ArrowRight':
          e.preventDefault();
          setCurrentTime(t => Math.min(duration, t + 1));
          break;
        case 's':
        case 'S':
          if (!e.metaKey && !e.ctrlKey) splitAtPlayhead();
          break;
        case 'z':
          if (e.metaKey || e.ctrlKey) { e.preventDefault(); undo(); }
          break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [duration, splitAtPlayhead, undo]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Timeline Editor</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setZoom(z => Math.max(1, z - 0.5))}
            className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors"
            title="Zoom out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-xs text-gray-500 w-10 text-center">{zoom}x</span>
          <button
            onClick={() => setZoom(z => Math.min(5, z + 0.5))}
            className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors"
            title="Zoom in"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Timeline */}
      <div
        ref={containerRef}
        className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4 overflow-x-auto"
      >
        {/* Time ruler */}
        <div className="relative h-6 mb-1" style={{ width: `${100 * zoom}%` }}>
          {Array.from({ length: Math.ceil(duration / 10) + 1 }, (_, i) => {
            const t = i * 10;
            return (
              <span
                key={t}
                className="absolute text-[10px] text-gray-600 -translate-x-1/2"
                style={{ left: `${(t / duration) * 100}%` }}
              >
                {formatTime(t)}
              </span>
            );
          })}
        </div>

        {/* Waveform canvas */}
        <canvas
          ref={canvasRef}
          className="w-full rounded-lg cursor-crosshair"
          style={{ height: 160, width: `${100 * zoom}%` }}
          onClick={handleCanvasClick}
          onMouseDown={handleCanvasMouseDown}
          onMouseMove={handleCanvasMouseMove}
          onMouseUp={handleCanvasMouseUp}
          onMouseLeave={handleCanvasMouseUp}
        />

        {/* Section labels bar */}
        <div className="relative h-8 mt-1" style={{ width: `${100 * zoom}%` }}>
          {sections.map(section => (
            <div
              key={section.id}
              className="absolute h-full rounded flex items-center justify-center text-xs font-medium text-white/80 overflow-hidden"
              style={{
                left: `${(section.startTime / duration) * 100}%`,
                width: `${((section.endTime - section.startTime) / duration) * 100}%`,
                backgroundColor: section.color + '40',
                borderLeft: `2px solid ${section.color}`,
              }}
            >
              {section.label}
            </div>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-4 bg-gray-800/60 border border-gray-700/50 rounded-lg p-3">
        <button
          onClick={() => setCurrentTime(0)}
          className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors"
          title="Go to start"
        >
          <SkipBack className="w-4 h-4" />
        </button>
        <button
          onClick={() => setPlaying(p => !p)}
          className="p-2 bg-[#4FC3F7] text-gray-900 rounded-full hover:bg-[#81D4FA] transition-colors"
        >
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
        </button>
        <button
          onClick={() => setCurrentTime(duration)}
          className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors"
          title="Go to end"
        >
          <SkipForward className="w-4 h-4" />
        </button>

        <span className="text-xs text-gray-400 font-mono w-20">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <div className="flex-1" />

        <button
          onClick={splitAtPlayhead}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 bg-gray-700/50 hover:bg-gray-700 rounded-lg transition-colors"
          title="Split at playhead (S)"
        >
          <Scissors className="w-3.5 h-3.5" />
          Split (S)
        </button>
        <button
          onClick={undo}
          disabled={history.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 bg-gray-700/50 hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-30"
          title="Undo (Cmd+Z)"
        >
          <Undo2 className="w-3.5 h-3.5" />
          Undo
        </button>
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-900 bg-[#4FC3F7] hover:bg-[#81D4FA] font-medium rounded-lg transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          Save Changes
        </button>
      </div>

      {/* Section list */}
      <div className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-4">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Sections</h3>
        <div className="space-y-2">
          {sections.map((section, i) => (
            <div key={section.id} className="flex items-center gap-3 p-2 bg-gray-900/30 rounded-lg">
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: section.color }}
              />
              <select
                value={section.label}
                onChange={e => {
                  pushHistory();
                  const label = e.target.value;
                  setSections(prev => prev.map((s, idx) =>
                    idx === i ? { ...s, label, color: SECTION_COLORS[label] || s.color } : s
                  ));
                }}
                className="px-2 py-1 bg-gray-900/50 border border-gray-700/30 rounded text-xs text-gray-300 focus:outline-none focus:border-[#4FC3F7]"
              >
                {SECTION_LABELS.map(l => (
                  <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>
                ))}
              </select>
              <span className="text-xs text-gray-500 font-mono flex-1">
                {formatTime(section.startTime)} - {formatTime(section.endTime)}
              </span>
              <span className="text-xs text-gray-600">
                {Math.round(section.endTime - section.startTime)}s
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Keyboard shortcuts */}
      <div className="text-xs text-gray-600 flex gap-6">
        <span>Space: Play/Pause</span>
        <span>Left/Right: Seek</span>
        <span>S: Split at playhead</span>
        <span>Cmd+Z: Undo</span>
        <span>Drag boundaries to adjust</span>
      </div>
    </div>
  );
}
