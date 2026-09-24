import React, { useState } from 'react';
import { X, QrCode, Camera, Flashlight, Image, Copy, Check, Share2, Sparkles } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { sound } from '../../utils/audio';

export const QrModal = () => {
  const { qrModal, setQrModal, user, startPaymentFlow } = useApp();
  const { isOpen, tab } = qrModal;

  const [activeTab, setActiveTab] = useState(tab || 'scan');
  const [flashOn, setFlashOn] = useState(false);
  const [copied, setCopied] = useState(false);
  const [requestAmount, setRequestAmount] = useState('');

  if (!isOpen) return null;

  const demoScans = [
    { name: "Starbucks Coffee", upiId: "starbucks@yesbank", category: "Dining" },
    { name: "Priya Patel", upiId: "priya.p@oksbi", category: "Payment" },
    { name: "Zomato Online", upiId: "zomato@icici", category: "Food Delivery" },
    { name: "Tata Power", upiId: "tatapower@billpay", category: "Bills" }
  ];

  const handleScanTarget = (target) => {
    sound.playTap();
    setQrModal({ isOpen: false });
    startPaymentFlow(target, '', target.category);
  };

  const handleCopyUpi = () => {
    navigator.clipboard?.writeText(user.upiId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[36px] bg-slate-900 border border-slate-700/80 p-6 shadow-2xl relative">
        {/* Close Button */}
        <button
          onClick={() => setQrModal({ isOpen: false })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Tab Switcher */}
        <div className="flex bg-slate-950 p-1 rounded-2xl mb-5 w-4/5 mx-auto">
          <button
            onClick={() => setActiveTab('scan')}
            className={`flex-1 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
              activeTab === 'scan' ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
            }`}
          >
            Scan Any QR
          </button>
          <button
            onClick={() => setActiveTab('myqr')}
            className={`flex-1 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
              activeTab === 'myqr' ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
            }`}
          >
            My QR Code
          </button>
        </div>

        {/* TAB 1: SCAN QR */}
        {activeTab === 'scan' && (
          <div className="space-y-4 text-center">
            {/* Camera Viewfinder */}
            <div className={`relative w-64 h-64 mx-auto rounded-3xl overflow-hidden border-2 transition-all ${
              flashOn ? 'bg-slate-700 border-white' : 'bg-slate-950 border-blue-500/40'
            } flex items-center justify-center`}>
              {/* Laser beam */}
              <div className="absolute left-4 right-4 h-0.5 bg-gradient-to-r from-transparent via-blue-400 to-transparent shadow-lg shadow-blue-500/80 animate-laser" />

              {/* Viewfinder Corners */}
              <div className="absolute top-4 left-4 w-6 h-6 border-t-2 border-l-2 border-blue-400" />
              <div className="absolute top-4 right-4 w-6 h-6 border-t-2 border-r-2 border-blue-400" />
              <div className="absolute bottom-4 left-4 w-6 h-6 border-b-2 border-l-2 border-blue-400" />
              <div className="absolute bottom-4 right-4 w-6 h-6 border-b-2 border-r-2 border-blue-400" />

              {/* Viewfinder Center Mock QR */}
              <div className="opacity-25 pointer-events-none">
                <QrCode className="w-36 h-36 text-white" />
              </div>

              <div className="absolute bottom-3 text-[11px] text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded-md">
                Align QR code within frame
              </div>
            </div>

            {/* Camera controls */}
            <div className="flex justify-center gap-4">
              <button
                onClick={() => setFlashOn(!flashOn)}
                className={`p-3 rounded-2xl border transition-all cursor-pointer ${
                  flashOn ? 'bg-amber-500/20 border-amber-400 text-amber-300' : 'bg-slate-800 border-slate-700 text-slate-300'
                }`}
                title="Toggle Torch"
              >
                <Flashlight className="w-5 h-5" />
              </button>
              <button
                onClick={() => handleScanTarget(demoScans[0])}
                className="p-3 rounded-2xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 cursor-pointer"
                title="Upload QR Image"
              >
                <Image className="w-5 h-5" />
              </button>
            </div>

            {/* Quick Demo Scan Targets */}
            <div className="pt-2 border-t border-slate-800">
              <span className="text-[11px] text-slate-400 block mb-2 font-medium">
                Tap to simulate scanning a merchant QR:
              </span>
              <div className="grid grid-cols-2 gap-2">
                {demoScans.map((target) => (
                  <button
                    key={target.name}
                    onClick={() => handleScanTarget(target)}
                    className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 text-left text-xs transition-colors cursor-pointer"
                  >
                    <p className="font-semibold text-white truncate">{target.name}</p>
                    <p className="text-[10px] text-blue-400">{target.category}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: MY QR */}
        {activeTab === 'myqr' && (
          <div className="space-y-4 text-center">
            {/* Generated QR card */}
            <div className="w-64 mx-auto rounded-3xl bg-white p-5 text-slate-900 shadow-2xl flex flex-col items-center">
              <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold text-sm mb-2 shadow-md">
                SP
              </div>
              <p className="text-xs font-bold text-slate-900">{user.name}</p>
              <p className="text-[10px] text-slate-500 font-mono mb-3">{user.upiId}</p>

              {/* QR Matrix SVG representation */}
              <div className="w-44 h-44 bg-slate-50 p-2 rounded-2xl border border-slate-200 flex items-center justify-center relative">
                <QrCode className="w-full h-full text-slate-900" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="w-8 h-8 rounded-lg bg-blue-600 border-2 border-white flex items-center justify-center text-white font-black text-xs">
                    ₹
                  </div>
                </div>
              </div>

              {requestAmount && (
                <div className="mt-3 px-3 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-bold">
                  Requested: ₹{requestAmount}
                </div>
              )}

              <p className="text-[9px] text-slate-400 mt-2">
                Scan with any UPI App • GPay • PhonePe • Paytm
              </p>
            </div>

            {/* Set Amount (optional) */}
            <div className="max-w-[240px] mx-auto">
              <input
                type="number"
                placeholder="Request specific amount (optional)"
                value={requestAmount}
                onChange={(e) => setRequestAmount(e.target.value)}
                className="w-full px-3 py-1.5 rounded-xl bg-slate-800 border border-slate-700 text-xs text-white text-center focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* Action buttons */}
            <div className="flex gap-2">
              <button
                onClick={handleCopyUpi}
                className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center justify-center gap-1.5 cursor-pointer transition-colors"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied ? 'Copied' : 'Copy UPI ID'}</span>
              </button>
              <button
                onClick={() => {
                  sound.playSuccessChime();
                  alert(`Senitenial QR Code for ${user.upiId} saved to photos!`);
                }}
                className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-600/30 cursor-pointer"
              >
                Download QR
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
