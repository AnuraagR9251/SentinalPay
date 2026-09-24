import React from 'react';
import {
  Utensils,
  ShoppingBag,
  Package,
  Car,
  Tv,
  Coffee,
  CheckCircle,
  Tag,
  ArrowRight
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const BusinessesSection = () => {
  const { merchants, startPaymentFlow } = useApp();

  const getMerchantIcon = (iconName) => {
    switch (iconName) {
      case 'Utensils': return <Utensils className="w-5 h-5 text-red-400" />;
      case 'ShoppingBag': return <ShoppingBag className="w-5 h-5 text-orange-400" />;
      case 'Package': return <Package className="w-5 h-5 text-amber-400" />;
      case 'Car': return <Car className="w-5 h-5 text-emerald-400" />;
      case 'Tv': return <Tv className="w-5 h-5 text-rose-400" />;
      case 'Coffee': return <Coffee className="w-5 h-5 text-amber-500" />;
      default: return <ShoppingBag className="w-5 h-5 text-blue-400" />;
    }
  };

  return (
    <section className="py-2">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-bold text-white tracking-tight font-heading">
          Businesses & Merchants
        </h2>
        <span className="text-xs text-blue-400 font-medium">Explore Offers</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {merchants.map((merchant) => (
          <div
            key={merchant.id}
            onClick={() => startPaymentFlow(
              {
                name: merchant.name,
                upiId: merchant.upiId,
                avatar: null,
                isMerchant: true
              },
              '',
              merchant.category
            )}
            className="p-3.5 rounded-2xl bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/60 hover:border-slate-600 transition-all cursor-pointer group flex flex-col justify-between"
          >
            <div className="flex items-start justify-between mb-2">
              <div className={`p-2.5 rounded-xl border ${merchant.bg}`}>
                {getMerchantIcon(merchant.icon)}
              </div>
              <div className="flex items-center gap-1 text-[10px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded-md font-medium">
                <CheckCircle className="w-3 h-3 text-blue-400" />
                <span>Verified</span>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-bold text-white group-hover:text-blue-400 transition-colors">
                {merchant.name}
              </h3>
              <p className="text-[11px] text-slate-400">
                {merchant.category}
              </p>
            </div>

            <div className="mt-3 pt-2 border-t border-slate-700/40 flex items-center justify-between text-[11px] text-amber-400">
              <div className="flex items-center gap-1 truncate">
                <Tag className="w-3 h-3 flex-shrink-0" />
                <span className="truncate">{merchant.cashbackOffer}</span>
              </div>
              <ArrowRight className="w-3 h-3 text-slate-500 group-hover:text-white group-hover:translate-x-0.5 transition-all flex-shrink-0 ml-1" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};
