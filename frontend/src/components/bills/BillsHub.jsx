import React, { useState } from 'react';
import {
  Zap,
  Smartphone,
  Wifi,
  Flame,
  Tv,
  Car,
  Droplet,
  CheckCircle,
  AlertCircle,
  ChevronRight,
  ArrowRight,
  Search
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const BillsHub = () => {
  const { bills, payBill, user, startPaymentFlow } = useApp();
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [billerSearch, setBillerSearch] = useState('');

  const categories = [
    { id: 'All', label: 'All Bills', icon: Zap },
    { id: 'Electricity', label: 'Electricity', icon: Zap },
    { id: 'Mobile', label: 'Recharge & Mobile', icon: Smartphone },
    { id: 'Broadband', label: 'Broadband / Fiber', icon: Wifi },
    { id: 'FASTag', label: 'FASTag Recharge', icon: Car },
    { id: 'DTH', label: 'DTH / Cable TV', icon: Tv },
    { id: 'Gas', label: 'Piped Gas / LPG', icon: Flame },
    { id: 'Water', label: 'Water & Taxes', icon: Droplet }
  ];

  const filteredBills = bills.filter(b => {
    const matchesCat = selectedCategory === 'All' || b.category.toLowerCase().includes(selectedCategory.toLowerCase());
    const matchesSearch = b.billerName.toLowerCase().includes(billerSearch.toLowerCase());
    return matchesCat && matchesSearch;
  });

  const getCategoryIcon = (cat) => {
    switch (cat.toLowerCase()) {
      case 'electricity': return <Zap className="w-5 h-5 text-amber-400" />;
      case 'mobile': return <Smartphone className="w-5 h-5 text-red-400" />;
      case 'broadband': return <Wifi className="w-5 h-5 text-blue-400" />;
      case 'piped gas':
      case 'gas': return <Flame className="w-5 h-5 text-orange-400" />;
      case 'fastag': return <Car className="w-5 h-5 text-emerald-400" />;
      case 'dth': return <Tv className="w-5 h-5 text-purple-400" />;
      default: return <Zap className="w-5 h-5 text-blue-400" />;
    }
  };

  const handleQuickRecharge = (provider) => {
    startPaymentFlow({
      name: `${provider} 5G Unlimited Plan`,
      upiId: `${provider.toLowerCase()}@recharge`,
      avatar: null,
      isBill: true
    }, 299, 'Mobile Recharge');
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto px-4 py-4 animate-fade-in">
      {/* Header Banner */}
      <div className="rounded-3xl p-6 bg-gradient-to-br from-blue-900/50 via-slate-900 to-indigo-950 border border-blue-500/20 shadow-xl">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs uppercase font-bold tracking-wider text-blue-400">
              Bharat BillPay (BBPS) Supported
            </span>
            <h1 className="text-2xl font-black text-white font-heading mt-1">
              Bills & Utilities Hub
            </h1>
            <p className="text-xs text-slate-300 mt-1 max-w-md">
              Instant bill payments with zero convenience fees and guaranteed cashback rewards on every payment.
            </p>
          </div>
          <div className="hidden sm:flex w-16 h-16 rounded-2xl bg-blue-600/20 border border-blue-500/30 items-center justify-center text-blue-400">
            <Zap className="w-8 h-8" />
          </div>
        </div>
      </div>

      {/* Category Icons Carousel */}
      <div className="flex gap-2 overflow-x-auto no-scrollbar py-1">
        {categories.map((c) => {
          const Icon = c.icon;
          const isSelected = selectedCategory === c.id;
          return (
            <button
              key={c.id}
              onClick={() => setSelectedCategory(c.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                isSelected
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20'
                  : 'bg-slate-800/80 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-700/60'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{c.label}</span>
            </button>
          );
        })}
      </div>

      {/* Pending / Due Bills Section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-bold text-white font-heading">
            Pending & Due Bills
          </h2>
          <span className="text-xs text-amber-400 font-medium">Auto-Fetch Active</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {filteredBills.map((bill) => {
            const isPaid = bill.status === 'Paid';
            return (
              <div
                key={bill.id}
                className="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                      {getCategoryIcon(bill.category)}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white">{bill.billerName}</h3>
                      <p className="text-[11px] text-slate-400">A/C: {bill.consumerNumber}</p>
                    </div>
                  </div>

                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                    isPaid
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-amber-500/20 text-amber-300'
                  }`}>
                    {bill.status}
                  </span>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
                  <div>
                    <span className="text-[10px] text-slate-400">Due Date: {bill.dueDate}</span>
                    <div className="text-base font-black text-white font-heading">
                      {user.currency}{bill.amountDue.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </div>
                  </div>

                  {isPaid ? (
                    <div className="flex items-center gap-1 text-emerald-400 text-xs font-semibold">
                      <CheckCircle className="w-4 h-4" />
                      <span>Paid</span>
                    </div>
                  ) : (
                    <button
                      onClick={() => payBill(bill.id)}
                      className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-md shadow-blue-600/30 transition-all cursor-pointer flex items-center gap-1.5"
                    >
                      <span>Pay Now</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quick Mobile 5G Recharges */}
      <div className="p-5 rounded-3xl bg-slate-800/40 border border-slate-700/60">
        <h3 className="text-sm font-bold text-white mb-1 font-heading">Popular Mobile Recharges</h3>
        <p className="text-xs text-slate-400 mb-3">1-Click recharge with instant 5G activation.</p>

        <div className="grid grid-cols-3 gap-2">
          {['Jio True 5G', 'Airtel Ultra 5G', 'Vi Unlimited'].map((provider) => (
            <button
              key={provider}
              onClick={() => handleQuickRecharge(provider)}
              className="p-3 rounded-2xl bg-slate-900/80 hover:bg-slate-900 border border-slate-800 hover:border-blue-500/50 text-left transition-all cursor-pointer group"
            >
              <Smartphone className="w-4 h-4 text-blue-400 mb-1 group-hover:scale-110 transition-transform" />
              <p className="text-xs font-bold text-white truncate">{provider}</p>
              <p className="text-[10px] text-emerald-400 font-semibold mt-0.5">₹299 (28 Days)</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
