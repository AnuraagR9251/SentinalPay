import React from 'react';
import { Shield, QrCode, Bell, Smartphone, Monitor, Moon, Sun, Search, Sparkles } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const Header = ({ searchQuery, setSearchQuery }) => {
  const {
    user,
    theme,
    setTheme,
    deviceFrame,
    setDeviceFrame,
    setQrModal,
    setNotificationModal,
    setProfileModal,
    notifications
  } = useApp();

  const unreadCount = notifications.filter(n => n.unread).length;

  return (
    <header className="sticky top-0 z-30 w-full backdrop-blur-xl bg-slate-900/80 dark:bg-slate-950/80 border-b border-slate-800/80 transition-colors">
      <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
        {/* Brand & Security Shield */}
        <div className="flex items-center gap-2.5">
          <div className="relative group cursor-pointer" onClick={() => setProfileModal({ isOpen: true })}>
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-emerald-500 p-[2px] shadow-lg shadow-blue-500/20">
              <div className="w-full h-full bg-slate-900 rounded-[14px] flex items-center justify-center">
                <Shield className="w-5 h-5 text-blue-400 group-hover:scale-110 transition-transform" />
              </div>
            </div>
            <span className="absolute -bottom-1 -right-1 w-3.5 h-3.5 bg-emerald-500 border-2 border-slate-900 rounded-full animate-pulse" />
          </div>

          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-lg font-bold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-300 to-emerald-400 bg-clip-text text-transparent font-heading">
                Senitenial Pay
              </span>
              <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                PRO
              </span>
            </div>
            <p className="text-[11px] text-slate-400 flex items-center gap-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              Sentinel AI Shield Active
            </p>
          </div>
        </div>

        {/* Global Search Bar */}
        <div className="hidden sm:flex flex-1 max-w-xs relative items-center">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
          <input
            type="text"
            placeholder="Pay friends, bills, UPI ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-slate-800/60 hover:bg-slate-800 text-sm text-slate-200 placeholder-slate-400 rounded-xl border border-slate-700/60 focus:outline-none focus:border-blue-500 transition-all"
          />
        </div>

        {/* Action icons & Toggles */}
        <div className="flex items-center gap-2">
          {/* Frame View Toggle (Desktop / Mobile Preview) */}
          <button
            onClick={() => setDeviceFrame(!deviceFrame)}
            title={deviceFrame ? "Switch to Full Desktop View" : "Switch to Mobile Device Frame"}
            className="p-2 rounded-xl bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/60 transition-all cursor-pointer"
          >
            {deviceFrame ? <Monitor className="w-4 h-4 text-indigo-400" /> : <Smartphone className="w-4 h-4 text-indigo-400" />}
          </button>

          {/* Theme Switcher */}
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="Toggle Dark / Light Theme"
            className="p-2 rounded-xl bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/60 transition-all cursor-pointer"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-blue-400" />}
          </button>

          {/* QR Scanner */}
          <button
            onClick={() => setQrModal({ isOpen: true, tab: 'scan' })}
            title="Scan any QR Code"
            className="p-2 rounded-xl bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 transition-all cursor-pointer"
          >
            <QrCode className="w-4 h-4" />
          </button>

          {/* Notifications */}
          <button
            onClick={() => setNotificationModal({ isOpen: true })}
            title="Notifications"
            className="relative p-2 rounded-xl bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/60 transition-all cursor-pointer"
          >
            <Bell className="w-4 h-4" />
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-[10px] font-bold text-white rounded-full flex items-center justify-center">
                {unreadCount}
              </span>
            )}
          </button>

          {/* User Profile Avatar */}
          <button
            onClick={() => setProfileModal({ isOpen: true })}
            className="relative ml-1 cursor-pointer focus:outline-none"
            title="Account & Security"
          >
            <img
              src={user.avatar}
              alt={user.name}
              className="w-9 h-9 rounded-xl object-cover ring-2 ring-blue-500/50 hover:ring-blue-400 transition-all"
            />
          </button>
        </div>
      </div>
    </header>
  );
};
