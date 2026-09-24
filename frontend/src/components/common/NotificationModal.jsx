import React from 'react';
import { X, Bell, Shield, Gift, AlertCircle, Check } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const NotificationModal = () => {
  const { notificationModal, setNotificationModal, notifications, setNotifications } = useApp();
  const { isOpen } = notificationModal;

  if (!isOpen) return null;

  const markAllRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, unread: false })));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-sm rounded-[32px] bg-slate-900 border border-slate-700/80 p-6 shadow-2xl relative">
        <button
          onClick={() => setNotificationModal({ isOpen: false })}
          className="absolute top-5 right-5 p-2 rounded-full bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Bell className="w-5 h-5 text-blue-400" />
            <h3 className="text-base font-bold text-white font-heading">Notifications</h3>
          </div>
          <button
            onClick={markAllRead}
            className="text-[11px] text-blue-400 hover:text-blue-300 font-semibold cursor-pointer"
          >
            Mark all read
          </button>
        </div>

        <div className="space-y-2.5 max-h-80 overflow-y-auto no-scrollbar">
          {notifications.map((n) => (
            <div
              key={n.id}
              className={`p-3 rounded-2xl border transition-all ${
                n.unread
                  ? 'bg-blue-950/40 border-blue-500/30'
                  : 'bg-slate-800/40 border-slate-700/50'
              }`}
            >
              <div className="flex items-start justify-between">
                <h4 className="text-xs font-bold text-white">{n.title}</h4>
                <span className="text-[10px] text-slate-400">{n.time}</span>
              </div>
              <p className="text-xs text-slate-300 mt-1">{n.message}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
