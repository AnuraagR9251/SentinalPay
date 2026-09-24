import React from 'react';
import { useApp } from '../../context/AppContext';
import { Sparkles, X, Smartphone } from 'lucide-react';

export const DeviceFrame = ({ children }) => {
  const { deviceFrame, setDeviceFrame } = useApp();

  if (!deviceFrame) {
    return <div className="min-h-screen pb-20">{children}</div>;
  }

  return (
    <div className="min-h-screen py-6 px-4 bg-slate-950 flex flex-col items-center justify-center">
      {/* Device frame header banner */}
      <div className="mb-4 flex items-center justify-between w-full max-w-sm px-2 text-xs text-slate-400">
        <div className="flex items-center gap-1.5 font-medium text-slate-300">
          <Smartphone className="w-4 h-4 text-blue-400" />
          <span>Mobile Device Simulation</span>
        </div>
        <button
          onClick={() => setDeviceFrame(false)}
          className="flex items-center gap-1 text-slate-400 hover:text-white px-2 py-1 rounded-lg bg-slate-800/80 border border-slate-700 cursor-pointer"
        >
          <span>Exit Frame</span>
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Simulated Phone Chassis */}
      <div className="relative w-full max-w-[420px] h-[860px] bg-slate-900 rounded-[52px] shadow-2xl shadow-blue-500/10 border-[10px] border-slate-800/90 ring-1 ring-slate-700/60 overflow-hidden flex flex-col">
        {/* Dynamic Island / Speaker Pill */}
        <div className="absolute top-2 left-1/2 -translate-x-1/2 w-28 h-6 bg-black rounded-full z-50 flex items-center justify-center">
          <div className="w-3 h-3 bg-slate-950 rounded-full border border-slate-800 mr-2" />
          <div className="w-2 h-2 bg-blue-500/40 rounded-full" />
        </div>

        {/* Scrollable screen viewport */}
        <div className="w-full h-full overflow-y-auto no-scrollbar pb-20 bg-slate-900 dark:bg-slate-950">
          {children}
        </div>
      </div>
    </div>
  );
};
