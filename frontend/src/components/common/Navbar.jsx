import React from 'react';
import { Home, ReceiptText, Users, CreditCard, History } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const Navbar = () => {
  const { activeTab, setActiveTab } = useApp();

  const navItems = [
    { id: 'home', label: 'Home', icon: Home },
    { id: 'bills', label: 'Bills', icon: ReceiptText },
    { id: 'split', label: 'Split', icon: Users },
    { id: 'cards', label: 'Cards & Banks', icon: CreditCard },
    { id: 'history', label: 'History', icon: History }
  ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-slate-900/90 dark:bg-slate-950/95 backdrop-blur-xl border-t border-slate-800/80 transition-colors">
      <div className="max-w-md mx-auto px-4 py-2 flex items-center justify-around">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`flex flex-col items-center gap-1 py-1 px-3 rounded-2xl transition-all cursor-pointer ${
                isActive
                  ? 'text-blue-400 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <div className={`p-1.5 rounded-xl transition-all ${
                isActive ? 'bg-blue-600/20 text-blue-400 scale-110 shadow-lg shadow-blue-500/10' : ''
              }`}>
                <Icon className="w-5 h-5" />
              </div>
              <span className="text-[11px] tracking-tight">{item.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
