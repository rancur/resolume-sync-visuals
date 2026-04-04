import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Columns2,
  SplitSquareHorizontal,
  ToggleLeft,
  ChevronLeft,
  ChevronRight,
  Play,
  Pause,
  SkipBack,
  SkipForward,
} from 'lucide-react';

type CompareMode = 'side-by-side' | 'slider' | 'toggle';

export default function ComparisonViewer() {
  const [mode, setMode] = useState<CompareMode>('side-by-side');
  const [videoA, setVideoA] = useState('');
  const [videoB, setVideoB] = useState('');
  const [labelA, setLabelA] = useState('Version A');
  const [labelB, setLabelB] = useState('Version B');
  const [showToggleA, setShowToggleA] = useState(true);
  const [sliderPos, setSliderPos] = useState(50);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const videoRefA = useRef<HTMLVideoElement>(null);
  const videoRefB = useRef<HTMLVideoElement>(null);
  const sliderContainerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  // Sync playback between both videos
  const syncPlay = useCallback(() => {
    videoRefA.current?.play();
    videoRefB.current?.play();
    setPlaying(true);
  }, []);

  const syncPause = useCallback(() => {
    videoRefA.current?.pause();
    videoRefB.current?.pause();
    setPlaying(false);
  }, []);

  const syncSeek = useCallback((time: number) => {
    if (videoRefA.current) videoRefA.current.currentTime = time;
    if (videoRefB.current) videoRefB.current.currentTime = time;
    setCurrentTime(time);
  }, []);

  const stepFrame = useCallback((forward: boolean) => {
    const delta = forward ? 1 / 30 : -1 / 30;
    const newTime = Math.max(0, Math.min(duration, currentTime + delta));
    syncSeek(newTime);
  }, [currentTime, duration, syncSeek]);

  useEffect(() => {
    const vid = videoRefA.current;
    if (!vid) return;
    const onTime = () => setCurrentTime(vid.currentTime);
    const onMeta = () => setDuration(vid.duration);
    vid.addEventListener('timeupdate', onTime);
    vid.addEventListener('loadedmetadata', onMeta);
    return () => {
      vid.removeEventListener('timeupdate', onTime);
      vid.removeEventListener('loadedmetadata', onMeta);
    };
  }, [videoA]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      switch (e.key) {
        case ' ':
          e.preventDefault();
          playing ? syncPause() : syncPlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          stepFrame(false);
          break;
        case 'ArrowRight':
          e.preventDefault();
          stepFrame(true);
          break;
        case 't':
          if (mode === 'toggle') setShowToggleA(!showToggleA);
          break;
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [playing, mode, showToggleA, syncPlay, syncPause, stepFrame]);

  // Slider drag
  const handleSliderMove = useCallback((e: MouseEvent | React.MouseEvent) => {
    if (!sliderContainerRef.current) return;
    const rect = sliderContainerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    setSliderPos((x / rect.width) * 100);
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (dragging.current) handleSliderMove(e);
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [handleSliderMove]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  const hasVideos = videoA && videoB;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Before / After Comparison</h1>
        <div className="flex items-center bg-gray-800/60 border border-gray-700/50 rounded-lg p-1">
          {([
            { mode: 'side-by-side' as CompareMode, icon: Columns2, label: 'Side by Side' },
            { mode: 'slider' as CompareMode, icon: SplitSquareHorizontal, label: 'Slider' },
            { mode: 'toggle' as CompareMode, icon: ToggleLeft, label: 'Toggle' },
          ]).map(({ mode: m, icon: Icon, label }) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors ${
                mode === m
                  ? 'bg-[#4FC3F7] text-gray-900 font-medium'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
              title={label}
            >
              <Icon className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* URL inputs */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Version A URL</label>
          <div className="flex gap-2">
            <input
              value={videoA}
              onChange={e => setVideoA(e.target.value)}
              placeholder="/api/preview/video/track_id_v1.mp4"
              className="flex-1 px-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
            <input
              value={labelA}
              onChange={e => setLabelA(e.target.value)}
              className="w-28 px-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Version B URL</label>
          <div className="flex gap-2">
            <input
              value={videoB}
              onChange={e => setVideoB(e.target.value)}
              placeholder="/api/preview/video/track_id_v2.mp4"
              className="flex-1 px-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[#4FC3F7]"
            />
            <input
              value={labelB}
              onChange={e => setLabelB(e.target.value)}
              className="w-28 px-3 py-2 bg-gray-800/60 border border-gray-700/50 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-[#4FC3F7]"
            />
          </div>
        </div>
      </div>

      {/* Comparison viewport */}
      {!hasVideos ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500 bg-gray-800/30 rounded-xl border border-gray-700/30">
          <SplitSquareHorizontal className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-lg font-medium text-gray-400">Enter two video URLs to compare</p>
          <p className="text-sm mt-1">Side-by-side, slider overlay, or toggle mode</p>
          <p className="text-xs mt-3 text-gray-600">
            Keyboard: Space (play/pause), Left/Right (frame step), T (toggle)
          </p>
        </div>
      ) : (
        <>
          <div className="bg-black rounded-xl overflow-hidden relative" style={{ aspectRatio: mode === 'side-by-side' ? '32/9' : '16/9' }}>
            {/* Side by Side */}
            {mode === 'side-by-side' && (
              <div className="flex h-full">
                <div className="flex-1 relative">
                  <video ref={videoRefA} src={videoA} className="w-full h-full object-contain" muted playsInline />
                  <span className="absolute top-2 left-2 px-2 py-0.5 bg-black/70 rounded text-xs text-gray-300">{labelA}</span>
                </div>
                <div className="w-px bg-gray-700" />
                <div className="flex-1 relative">
                  <video ref={videoRefB} src={videoB} className="w-full h-full object-contain" muted playsInline />
                  <span className="absolute top-2 left-2 px-2 py-0.5 bg-black/70 rounded text-xs text-gray-300">{labelB}</span>
                </div>
              </div>
            )}

            {/* Slider */}
            {mode === 'slider' && (
              <div
                ref={sliderContainerRef}
                className="relative h-full cursor-ew-resize"
                onMouseDown={e => { dragging.current = true; handleSliderMove(e); }}
              >
                {/* Video B (full) */}
                <video ref={videoRefB} src={videoB} className="absolute inset-0 w-full h-full object-contain" muted playsInline />
                {/* Video A (clipped) */}
                <div className="absolute inset-0 overflow-hidden" style={{ width: `${sliderPos}%` }}>
                  <video ref={videoRefA} src={videoA} className="w-full h-full object-contain" style={{ minWidth: sliderContainerRef.current ? `${sliderContainerRef.current.clientWidth}px` : '100%' }} muted playsInline />
                </div>
                {/* Slider line */}
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-white/80 pointer-events-none"
                  style={{ left: `${sliderPos}%` }}
                >
                  <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 bg-white/90 rounded-full flex items-center justify-center shadow-lg">
                    <ChevronLeft className="w-3 h-3 text-gray-800" />
                    <ChevronRight className="w-3 h-3 text-gray-800" />
                  </div>
                </div>
                <span className="absolute top-2 left-2 px-2 py-0.5 bg-black/70 rounded text-xs text-gray-300">{labelA}</span>
                <span className="absolute top-2 right-2 px-2 py-0.5 bg-black/70 rounded text-xs text-gray-300">{labelB}</span>
              </div>
            )}

            {/* Toggle */}
            {mode === 'toggle' && (
              <div
                className="relative h-full cursor-pointer"
                onClick={() => setShowToggleA(!showToggleA)}
              >
                <video
                  ref={videoRefA}
                  src={videoA}
                  className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-200 ${showToggleA ? 'opacity-100' : 'opacity-0'}`}
                  muted
                  playsInline
                />
                <video
                  ref={videoRefB}
                  src={videoB}
                  className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-200 ${showToggleA ? 'opacity-0' : 'opacity-100'}`}
                  muted
                  playsInline
                />
                <span className="absolute top-2 left-2 px-2 py-0.5 bg-black/70 rounded text-xs text-gray-300">
                  {showToggleA ? labelA : labelB}
                </span>
                <span className="absolute bottom-2 left-1/2 -translate-x-1/2 px-3 py-1 bg-black/70 rounded text-xs text-gray-400">
                  Click or press T to toggle
                </span>
              </div>
            )}
          </div>

          {/* Playback controls */}
          <div className="flex items-center gap-4 bg-gray-800/60 border border-gray-700/50 rounded-lg p-3">
            <button onClick={() => stepFrame(false)} className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Previous frame">
              <SkipBack className="w-4 h-4" />
            </button>
            <button
              onClick={playing ? syncPause : syncPlay}
              className="p-2 bg-[#4FC3F7] text-gray-900 rounded-full hover:bg-[#81D4FA] transition-colors"
            >
              {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            </button>
            <button onClick={() => stepFrame(true)} className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Next frame">
              <SkipForward className="w-4 h-4" />
            </button>

            <span className="text-xs text-gray-500 w-16">{formatTime(currentTime)}</span>
            <div className="flex-1">
              <input
                type="range"
                min={0}
                max={duration || 1}
                step={0.033}
                value={currentTime}
                onChange={e => syncSeek(Number(e.target.value))}
                className="w-full accent-[#4FC3F7] h-1"
              />
            </div>
            <span className="text-xs text-gray-500 w-16 text-right">{formatTime(duration)}</span>
          </div>
        </>
      )}
    </div>
  );
}
