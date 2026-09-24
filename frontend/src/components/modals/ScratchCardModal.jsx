import React, { useRef, useEffect, useState } from 'react';
import { X, Sparkles, Award, Gift, Copy, Check, ArrowRight } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { sound } from '../../utils/audio';

export const ScratchCardModal = () => {
  const { scratchCardModal, setScratchCardModal, claimScratchCard, user } = useApp();
  const { isOpen, reward } = scratchCardModal;

  const canvasRef = useRef(null);
  const [isScratched, setIsScratched] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen || !reward) return;

    if (reward.isScratched) {
      setIsScratched(true);
      return;
    }

    setIsScratched(false);

    // Setup HTML5 canvas overlay
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    // Draw holographic silver scratch coating
    const grad = ctx.createLinearGradient(0, 0, width, height);
    grad.addColorStop(0, '#64748b');
    grad.addColorStop(0.3, '#94a3b8');
    grad.addColorStop(0.5, '#cbd5e1');
    grad.addColorStop(0.7, '#94a3b8');
    grad.addColorStop(1, '#475569');

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, width, height);

    // Decorative text on coating
    ctx.font = 'bold 15px sans-serif';
    ctx.fillStyle = '#1e293b';
    ctx.textAlign = 'center';
    ctx.fillText('⚡ SENITENIAL REWARDS', width / 2, height / 2 - 10);
    ctx.font = '12px sans-serif';
    ctx.fillStyle = '#334155';
    ctx.fillText('Scratch with mouse or finger', width / 2, height / 2 + 15);

    let isDrawing = false;
    let scratchedPixels = 0;
    const totalPixels = width * height;

    const getPos = (e) => {
      const rect = canvas.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      return {
        x: (clientX - rect.left) * (canvas.width / rect.width),
        y: (clientY - rect.top) * (canvas.height / rect.height)
      };
    };

    const scratch = (e) => {
      if (!isDrawing) return;
      const { x, y } = getPos(e);

      ctx.globalCompositeOperation = 'destination-out';
      ctx.beginPath();
      ctx.arc(x, y, 24, 0, Math.PI * 2);
      ctx.fill();

      sound.playScratch();

      scratchedPixels += 80;
      if (scratchedPixels > totalPixels * 0.35 && !isScratched) {
        setIsScratched(true);
        claimScratchCard(reward.id, reward.type === 'cashback' ? reward.amount : 0);
      }
    };

    const handleStart = (e) => {
      isDrawing = true;
      scratch(e);
    };

    const handleEnd = () => {
      isDrawing = false;
    };

    canvas.addEventListener('mousedown', handleStart);
    canvas.addEventListener('mousemove', scratch);
    window.addEventListener('mouseup', handleEnd);

    canvas.addEventListener('touchstart', handleStart);
    canvas.addEventListener('touchmove', scratch);
    window.addEventListener('touchend', handleEnd);

    return () => {
      canvas.removeEventListener('mousedown', handleStart);
      canvas.removeEventListener('mousemove', scratch);
      window.removeEventListener('mouseup', handleEnd);

      canvas.removeEventListener('touchstart', handleStart);
      canvas.removeEventListener('touchmove', scratch);
      window.removeEventListener('touchend', handleEnd);
    };
  }, [isOpen, reward]);

  if (!isOpen || !reward) return null;

  const handleCopyCode = () => {
    navigator.clipboard?.writeText(reward.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700/80 p-6 text-center shadow-2xl relative">
        {/* Close Button */}
        <button
          onClick={() => setScratchCardModal({ isOpen: false, reward: null })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Header */}
        <div className="flex items-center justify-center gap-1.5 text-xs text-amber-400 font-semibold mb-2">
          <Sparkles className="w-4 h-4" />
          <span>SENITENIAL SCRATCH & WIN</span>
        </div>

        <h3 className="text-lg font-bold text-white mb-4 font-heading">
          {isScratched ? "Congratulations! 🎉" : "Scratch to Reveal Reward"}
        </h3>

        {/* Scratch Card Frame */}
        <div className="relative w-64 h-64 mx-auto rounded-3xl overflow-hidden shadow-2xl border-2 border-amber-500/40 bg-gradient-to-tr from-amber-600/30 via-slate-900 to-indigo-950 flex flex-col items-center justify-center p-4 select-none">
          {/* Revealed Reward under canvas */}
          <div className="text-center space-y-2">
            <div className="w-16 h-16 rounded-2xl bg-amber-500/20 text-amber-400 flex items-center justify-center mx-auto border border-amber-500/30">
              {reward.type === 'cashback' ? (
                <Award className="w-9 h-9" />
              ) : (
                <Gift className="w-9 h-9" />
              )}
            </div>

            <div>
              <div className="text-4xl font-black text-amber-400 font-heading">
                {reward.type === 'cashback' ? `${user.currency}${reward.amount}` : `${reward.amount}% OFF`}
              </div>
              <p className="text-sm font-bold text-white mt-1">
                {reward.title}
              </p>
              <p className="text-xs text-slate-300 max-w-[200px] mx-auto mt-1">
                {reward.description}
              </p>
            </div>

            {reward.type === 'cashback' && (
              <span className="inline-block px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px] font-bold">
                ✓ Credited to Senitenial Wallet
              </span>
            )}
          </div>

          {/* Canvas Scratch Layer */}
          {!reward.isScratched && !isScratched && (
            <canvas
              ref={canvasRef}
              width={256}
              height={256}
              className="absolute inset-0 w-full h-full cursor-pointer touch-none"
            />
          )}
        </div>

        {/* Footer info & Voucher Code */}
        {isScratched && (
          <div className="mt-4 space-y-3">
            {reward.code && reward.code !== "CLAIMED" && (
              <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs">
                <span className="font-mono text-slate-300 font-bold">{reward.code}</span>
                <button
                  onClick={handleCopyCode}
                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 cursor-pointer flex items-center gap-1"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            )}

            <button
              onClick={() => setScratchCardModal({ isOpen: false, reward: null })}
              className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-600/30 cursor-pointer"
            >
              Collect & Return
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
