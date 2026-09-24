// ==========================================
// Senetinal Pay - Complete JavaScript Core
// ==========================================

// --- Web Audio API Synthesizer (No external mp3 needed) ---
class SoundFX {
  constructor() {
    this.ctx = null;
    this.enabled = true;
  }

  init() {
    if (!this.ctx && typeof window !== 'undefined') {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        this.ctx = new AudioContext();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  playSuccessChime() {
    if (!this.enabled) return;
    try {
      this.init();
      if (!this.ctx) return;
      const now = this.ctx.currentTime;
      const notes = [
        { freq: 523.25, time: 0.0, dur: 0.4 },
        { freq: 659.25, time: 0.12, dur: 0.45 },
        { freq: 783.99, time: 0.24, dur: 0.8 },
        { freq: 1046.50, time: 0.36, dur: 1.2 }
      ];
      notes.forEach(({ freq, time, dur }) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, now + time);
        gain.gain.setValueAtTime(0, now + time);
        gain.gain.linearRampToValueAtTime(0.25, now + time + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + time + dur);
        osc.connect(gain);
        gain.connect(this.ctx.destination);
        osc.start(now + time);
        osc.stop(now + time + dur + 0.05);
      });
    } catch (e) {}
  }

  playPinDigit() {
    if (!this.enabled) return;
    try {
      this.init();
      if (!this.ctx) return;
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(800, now);
      osc.frequency.exponentialRampToValueAtTime(400, now + 0.06);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.06);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start(now);
      osc.stop(now + 0.07);
    } catch (e) {}
  }

  playScratch() {
    if (!this.enabled) return;
    try {
      this.init();
      if (!this.ctx) return;
      const bufferSize = this.ctx.sampleRate * 0.04;
      const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        data[i] = Math.random() * 2 - 1;
      }
      const noise = this.ctx.createBufferSource();
      noise.buffer = buffer;
      const filter = this.ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.value = 1400;
      const gain = this.ctx.createGain();
      gain.gain.setValueAtTime(0.04, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.04);
      noise.connect(filter);
      filter.connect(gain);
      gain.connect(this.ctx.destination);
      noise.start();
    } catch (e) {}
  }

  playTap() {
    if (!this.enabled) return;
    try {
      this.init();
      if (!this.ctx) return;
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(600, now);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start(now);
      osc.stop(now + 0.05);
    } catch (e) {}
  }
}

const sound = new SoundFX();

// --- INITIAL STATE & DATA ---
const DEFAULT_STATE = {
  walletBalance: 24850.00,
  isBalanceVisible: true,
  theme: 'dark',
  deviceFrame: false,
  soundEnabled: true,
  contacts: [
    { id: "c1", name: "Priya Patel", upiId: "priya.p@oksbi", phone: "+91 98234 56781", avatar: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&q=80&w=150", recentAmount: 850, verified: true },
    { id: "c2", name: "Rohan Verma", upiId: "rohanv@senetinal", phone: "+91 97112 34567", avatar: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&q=80&w=150", recentAmount: 2400, verified: true },
    { id: "c3", name: "Ananya Iyer", upiId: "ananya.iyer@okhdfcbank", phone: "+91 96543 21098", avatar: "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&q=80&w=150", recentAmount: 500, verified: true },
    { id: "c4", name: "Devendra Singh", upiId: "dev.singh@senetinal", phone: "+91 99887 76655", avatar: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&q=80&w=150", recentAmount: 1200, verified: true },
    { id: "c5", name: "Sneha Roy", upiId: "sneha.roy@okaxis", phone: "+91 91234 87654", avatar: "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&q=80&w=150", recentAmount: 1500, verified: true },
    { id: "c6", name: "Vikram Malhotra", upiId: "vikram.m@paytm", phone: "+91 93456 12789", avatar: "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?auto=format&fit=crop&q=80&w=150", recentAmount: 320, verified: false }
  ],
  merchants: [
    { id: "m1", name: "Zomato", category: "Food Delivery", upiId: "zomato@icici", offer: "Flat ₹50 cashback", icon: "utensils", color: "text-red-400 bg-red-500/10 border-red-500/20" },
    { id: "m2", name: "Swiggy", category: "Food & Instamart", upiId: "swiggy@hdfcbank", offer: "Up to ₹100 scratch card", icon: "shopping-bag", color: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
    { id: "m3", name: "Amazon India", category: "Online Shopping", upiId: "amazonpay@apl", offer: "5% Sentinel Cashback", icon: "package", color: "text-amber-400 bg-amber-500/10 border-amber-500/20" },
    { id: "m4", name: "Uber", category: "Rides & Cabs", upiId: "uber.india@axisbank", offer: "₹40 off 1st ride", icon: "car", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
    { id: "m5", name: "Netflix India", category: "Entertainment", upiId: "netflix@citi", offer: "Auto-pay reward active", icon: "tv", color: "text-rose-400 bg-rose-500/10 border-rose-500/20" },
    { id: "m6", name: "Starbucks", category: "Coffee & Dining", upiId: "starbucks@yesbank", offer: "Free upgrade scratch reward", icon: "coffee", color: "text-amber-500 bg-amber-500/10 border-amber-500/20" }
  ],
  bills: [
    { id: "b1", billerName: "Tata Power Mumbai", category: "Electricity", consumerNumber: "900234110", amountDue: 1840.00, dueDate: "2026-09-28", status: "Due Soon", icon: "zap" },
    { id: "b2", billerName: "Jio Fiber Ultra", category: "Broadband", consumerNumber: "022-4912984", amountDue: 1179.00, dueDate: "2026-10-02", status: "Upcoming", icon: "wifi" },
    { id: "b3", billerName: "Airtel 5G Postpaid", category: "Mobile", consumerNumber: "9876543210", amountDue: 699.00, dueDate: "2026-09-30", status: "Due Soon", icon: "smartphone" },
    { id: "b4", billerName: "Mahanagar Gas (MGL)", category: "Gas", consumerNumber: "MG-889123", amountDue: 740.00, dueDate: "2026-10-05", status: "Upcoming", icon: "flame" }
  ],
  rewards: [
    { id: "r1", type: "cashback", title: "Cashback Reward", amount: 65, isScratched: false },
    { id: "r2", type: "cashback", title: "Weekend Bonus", amount: 40, isScratched: false },
    { id: "r3", type: "cashback", title: "Cashback Won", amount: 45, isScratched: true, scratchedAt: "Yesterday" }
  ],
  splits: [
    { id: "s1", title: "Goa Beach Villa Weekend", totalAmount: 14200, myShare: 3550, members: ["Aarav (You)", "Priya", "Rohan", "Sneha"], settled: false },
    { id: "s2", title: "Apartment 402 Wifi & Grocery", totalAmount: 4800, myShare: 1600, members: ["Aarav (You)", "Devendra", "Ananya"], settled: false }
  ],
  transactions: [
    { id: "tx1", title: "Priya Patel", upiId: "priya.p@oksbi", type: "debit", amount: 850.00, category: "Food & Dining", timestamp: "Today, 11:42 AM", method: "SBI •••• 4821", utr: "SENT489201948201", note: "Brunch split 🥞" },
    { id: "tx2", title: "Rohan Verma", upiId: "rohanv@senetinal", type: "credit", amount: 2400.00, category: "Transfer", timestamp: "Yesterday, 8:15 PM", method: "Senetinal Wallet", utr: "SENT892019204812", note: "Goa flight ticket share" },
    { id: "tx3", title: "Tata Power Electricity", upiId: "tatapower@billpay", type: "debit", amount: 1640.00, category: "Utility Bills", timestamp: "21 Sep 2026", method: "HDFC •••• 9012", utr: "SENT338910482910", note: "Bill Payment - Consumer #900234110" },
    { id: "tx4", title: "Senetinal Scratch Cashback", upiId: "rewards@senetinal", type: "credit", amount: 45.00, category: "Rewards", timestamp: "20 Sep 2026", method: "Senetinal Wallet", utr: "SENT999018472911", note: "GPay Scratch Card Cashback" },
    { id: "tx5", title: "Starbucks Reserve", upiId: "starbucks@yesbank", type: "debit", amount: 490.00, category: "Coffee & Dining", timestamp: "19 Sep 2026", method: "Metal Black •••• 4298", utr: "SENT772819283719", note: "Caramel Macchiato" }
  ],
  banks: [
    { id: "b-sbi", name: "State Bank of India", acc: "•••• 4821", balance: 58320.00, isPrimary: true, logo: "SBI" },
    { id: "b-hdfc", name: "HDFC Bank", acc: "•••• 9012", balance: 112400.00, isPrimary: false, logo: "HDFC" },
    { id: "b-vault", name: "Senetinal Reserve Vault", acc: "•••• 7733", balance: 250000.00, isPrimary: false, logo: "VAULT" }
  ],
  cards: [
    { id: "c1", number: "4532 •••• •••• 4298", holder: "Aarav Sharma", expiry: "09/28", cvv: "782", variant: "Metal Black Edition", isFrozen: false }
  ]
};

// Load or Seed state from localStorage
let appState = (() => {
  const saved = localStorage.getItem('senetinalpay_state');
  if (saved) {
    try { return JSON.parse(saved); } catch (e) {}
  }
  return DEFAULT_STATE;
})();

function saveState() {
  localStorage.setItem('senetinalpay_state', JSON.stringify(appState));
}

// Current active flow variables
let activePayment = null;
let currentEnteredPin = '';
let currentScratchReward = null;
let currentTransactionReceipt = null;

// --- INITIAL RENDER ---
document.addEventListener('DOMContentLoaded', () => {
  renderAll();
  lucide.createIcons();
});

function renderAll() {
  renderBalance();
  renderPeople();
  renderBusinesses();
  renderRewards();
  renderTransactions();
  renderBills();
  renderSplits();
  renderBanks();
  lucide.createIcons();
}

// --- BALANCE ---
function renderBalance() {
  const balanceEl = document.getElementById('home-balance-display');
  if (balanceEl) {
    balanceEl.textContent = appState.isBalanceVisible
      ? `₹ ${appState.walletBalance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
      : '••••••••';
  }
}

function toggleBalanceVisibility() {
  appState.isBalanceVisible = !appState.isBalanceVisible;
  saveState();
  renderBalance();
  const icon = document.getElementById('balance-eye-icon');
  if (icon) {
    icon.setAttribute('data-lucide', appState.isBalanceVisible ? 'eye' : 'eye-off');
    lucide.createIcons();
  }
}

// --- CONTACTS ---
function renderPeople(query = '') {
  const grid = document.getElementById('people-grid');
  if (!grid) return;

  const filtered = appState.contacts.filter(c =>
    c.name.toLowerCase().includes(query.toLowerCase()) || c.phone.includes(query)
  );

  grid.innerHTML = `
    <div class="flex flex-col items-center">
      <button onclick="promptAddContact()" class="w-14 h-14 rounded-full border-2 border-dashed border-slate-700 hover:border-blue-500 bg-slate-800/40 text-slate-400 hover:text-blue-400 flex items-center justify-center transition-all cursor-pointer">
        <i data-lucide="user-plus" class="w-5 h-5"></i>
      </button>
      <span class="mt-1.5 text-xs text-slate-400 font-medium text-center truncate max-w-[64px]">Add New</span>
    </div>
  ` + filtered.map(c => `
    <button onclick="startPaymentFlow('${c.name}', '${c.upiId}', '${c.avatar}')" class="flex flex-col items-center group cursor-pointer">
      <div class="relative">
        <img src="${c.avatar}" alt="${c.name}" class="w-14 h-14 rounded-full object-cover ring-2 ring-slate-800 group-hover:ring-blue-500 group-hover:scale-105 transition-all shadow-md" />
        ${c.verified ? '<div class="absolute -bottom-0.5 -right-0.5 bg-blue-600 rounded-full p-0.5 text-white ring-2 ring-slate-900"><i data-lucide="check" class="w-2.5 h-2.5"></i></div>' : ''}
      </div>
      <span class="mt-1.5 text-xs text-slate-200 group-hover:text-blue-400 font-medium text-center truncate max-w-[68px]">${c.name.split(' ')[0]}</span>
      <span class="text-[10px] text-slate-500">₹${c.recentAmount}</span>
    </button>
  `).join('');
}

function promptAddContact() {
  const name = prompt("Enter Contact Name:");
  if (!name) return;
  const phone = prompt("Enter Phone Number (e.g. +91 98111 22334):") || "+91 98000 00000";
  const upiId = prompt("Enter UPI ID (optional):") || `${name.toLowerCase().replace(/\s+/g, '')}@senetinal`;

  appState.contacts.unshift({
    id: `c_${Date.now()}`,
    name,
    phone,
    upiId,
    avatar: "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&q=80&w=150",
    recentAmount: 0,
    verified: true
  });
  saveState();
  renderPeople();
  lucide.createIcons();
}

// --- BUSINESSES ---
function renderBusinesses() {
  const grid = document.getElementById('businesses-grid');
  if (!grid) return;

  grid.innerHTML = appState.merchants.map(m => `
    <div onclick="startPaymentFlow('${m.name}', '${m.upiId}')" class="p-3.5 rounded-2xl bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/60 hover:border-slate-600 transition-all cursor-pointer flex flex-col justify-between group">
      <div class="flex items-start justify-between mb-2">
        <div class="p-2.5 rounded-xl border ${m.color}">
          <i data-lucide="${m.icon}" class="w-5 h-5"></i>
        </div>
        <div class="flex items-center gap-1 text-[10px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded-md font-medium">
          <i data-lucide="check-circle-2" class="w-3 h-3"></i>
          <span>Verified</span>
        </div>
      </div>
      <div>
        <h3 class="text-sm font-bold text-white group-hover:text-blue-400 transition-colors">${m.name}</h3>
        <p class="text-[11px] text-slate-400">${m.category}</p>
      </div>
      <div class="mt-3 pt-2 border-t border-slate-700/40 flex items-center justify-between text-[11px] text-amber-400">
        <span class="truncate">${m.offer}</span>
        <i data-lucide="arrow-right" class="w-3 h-3 text-slate-500 group-hover:text-white ml-1"></i>
      </div>
    </div>
  `).join('');
}

// --- REWARDS & SCRATCH CARDS ---
function renderRewards() {
  const carousel = document.getElementById('scratch-cards-carousel');
  const totalDisplay = document.getElementById('total-cashback-display');
  const statusText = document.getElementById('rewards-status-text');

  const totalWon = appState.rewards.filter(r => r.isScratched).reduce((s, r) => s + r.amount, 450);
  if (totalDisplay) totalDisplay.textContent = `₹${totalWon}`;

  const unscratched = appState.rewards.filter(r => !r.isScratched);
  if (statusText) {
    statusText.textContent = unscratched.length > 0
      ? `${unscratched.length} scratch card${unscratched.length > 1 ? 's' : ''} waiting to be scratched!`
      : 'Keep paying with Senetinal Pay to win more!';
  }

  if (!carousel) return;

  carousel.innerHTML = appState.rewards.map(r => {
    if (!r.isScratched) {
      return `
        <div onclick="openScratchModal('${r.id}')" class="flex-shrink-0 w-36 h-44 rounded-2xl bg-gradient-to-br from-indigo-700 via-purple-700 to-pink-600 p-[2px] shadow-lg shadow-purple-900/30 cursor-pointer group hover:scale-105 transition-all">
          <div class="w-full h-full bg-slate-900/90 rounded-[14px] p-3 flex flex-col items-center justify-between text-center relative overflow-hidden">
            <span class="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold uppercase border border-amber-400/30 animate-pulse">Scratch to Win</span>
            <div class="my-auto">
              <i data-lucide="sparkles" class="w-8 h-8 text-amber-400 mx-auto"></i>
              <p class="text-xs font-bold text-white mt-2 leading-tight">Surprise Cashback</p>
            </div>
            <span class="text-[10px] text-slate-400">Tap & scratch</span>
          </div>
        </div>
      `;
    } else {
      return `
        <div onclick="openScratchModal('${r.id}')" class="flex-shrink-0 w-36 h-44 rounded-2xl bg-slate-800/80 border border-slate-700/80 p-3 flex flex-col justify-between cursor-pointer hover:border-slate-600 transition-all">
          <div class="flex items-center justify-between">
            <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[9px] font-bold">CLAIMED</span>
            <i data-lucide="award" class="w-4 h-4 text-emerald-400"></i>
          </div>
          <div class="my-auto text-center">
            <div class="text-2xl font-black text-emerald-400 font-heading">₹${r.amount}</div>
            <p class="text-xs font-semibold text-white mt-1">Cashback Won</p>
          </div>
          <span class="text-[10px] text-slate-400 text-center">${r.scratchedAt || 'Claimed'}</span>
        </div>
      `;
    }
  }).join('');
}

// --- TRANSACTIONS ---
function renderTransactions(filter = 'all') {
  const recentList = document.getElementById('recent-transactions-list');
  const historyList = document.getElementById('history-transactions-list');

  // Compute metrics
  const totalDebit = appState.transactions.filter(t => t.type === 'debit').reduce((sum, t) => sum + t.amount, 0);
  const totalCredit = appState.transactions.filter(t => t.type === 'credit').reduce((sum, t) => sum + t.amount, 0);

  const debitEl = document.getElementById('total-debited-display');
  const creditEl = document.getElementById('total-credited-display');
  if (debitEl) debitEl.textContent = `₹ ${totalDebit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
  if (creditEl) creditEl.textContent = `₹ ${totalCredit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;

  const renderItem = (tx) => {
    const isDebit = tx.type === 'debit';
    return `
      <div onclick="openReceiptModal('${tx.id}')" class="p-3.5 rounded-2xl bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/60 hover:border-slate-600 transition-all flex items-center justify-between cursor-pointer group">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-2xl flex items-center justify-center ${isDebit ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'}">
            <i data-lucide="${isDebit ? 'arrow-up-right' : 'arrow-down-left'}" class="w-5 h-5"></i>
          </div>
          <div>
            <h4 class="text-sm font-bold text-white group-hover:text-blue-400 transition-colors">${tx.title}</h4>
            <p class="text-[11px] text-slate-400">${tx.timestamp} • ${tx.category}</p>
          </div>
        </div>
        <div class="text-right">
          <div class="text-sm font-bold font-heading ${isDebit ? 'text-white' : 'text-emerald-400'}">
            ${isDebit ? '-' : '+'}₹${tx.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <span class="text-[10px] text-slate-500 font-mono">${tx.method.split(' ')[0]}</span>
        </div>
      </div>
    `;
  };

  if (recentList) {
    recentList.innerHTML = appState.transactions.slice(0, 4).map(renderItem).join('');
  }

  if (historyList) {
    const filtered = appState.transactions.filter(t => {
      if (filter === 'all') return true;
      if (filter === 'debit') return t.type === 'debit';
      if (filter === 'credit') return t.type === 'credit';
      if (filter === 'bills') return t.category.toLowerCase().includes('bill');
      if (filter === 'rewards') return t.category.toLowerCase().includes('reward');
      return true;
    });

    historyList.innerHTML = filtered.length > 0
      ? filtered.map(renderItem).join('')
      : '<p class="text-center text-xs text-slate-500 py-8">No matching transactions found.</p>';
  }
}

// --- BILLS ---
function renderBills() {
  const container = document.getElementById('bills-container');
  if (!container) return;

  container.innerHTML = appState.bills.map(b => `
    <div class="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between">
      <div class="flex items-start justify-between">
        <div class="flex items-center gap-3">
          <div class="p-2.5 rounded-xl bg-slate-900 border border-slate-800 text-blue-400">
            <i data-lucide="${b.icon}" class="w-5 h-5"></i>
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">${b.billerName}</h3>
            <p class="text-[11px] text-slate-400">A/C: ${b.consumerNumber}</p>
          </div>
        </div>
        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${b.status === 'Paid' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-300'}">
          ${b.status}
        </span>
      </div>
      <div class="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
        <div>
          <span class="text-[10px] text-slate-400">Due: ${b.dueDate}</span>
          <div class="text-base font-black text-white font-heading">₹${b.amountDue.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div>
        </div>
        ${b.status === 'Paid'
          ? '<span class="text-xs text-emerald-400 font-semibold flex items-center gap-1"><i data-lucide="check" class="w-4 h-4"></i> Paid</span>'
          : `<button onclick="payBillDirect('${b.id}')" class="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-md shadow-blue-600/30 transition-all cursor-pointer">Pay Now</button>`
        }
      </div>
    </div>
  `).join('');
}

function payBillDirect(billId) {
  const bill = appState.bills.find(b => b.id === billId);
  if (!bill) return;
  startPaymentFlow(bill.billerName, `${bill.category.toLowerCase()}@billpay`, null, bill.amountDue);
}

// --- SPLITS ---
function renderSplits() {
  const container = document.getElementById('splits-container');
  if (!container) return;

  container.innerHTML = appState.splits.map(s => `
    <div class="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between">
      <div>
        <div class="flex items-start justify-between">
          <h3 class="text-sm font-bold text-white font-heading">${s.title}</h3>
          <span class="px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 text-[10px] font-bold">Active</span>
        </div>
        <p class="text-[11px] text-slate-400 mt-0.5">${s.members.join(', ')}</p>
        <div class="grid grid-cols-2 gap-2 mt-4 p-3 rounded-xl bg-slate-900/80 border border-slate-800">
          <div>
            <span class="text-[10px] text-slate-400">Total Bill</span>
            <p class="text-base font-extrabold text-white">₹${s.totalAmount.toLocaleString('en-IN')}</p>
          </div>
          <div>
            <span class="text-[10px] text-indigo-400 font-semibold">Your Share</span>
            <p class="text-base font-extrabold text-emerald-400">₹${s.myShare.toLocaleString('en-IN')}</p>
          </div>
        </div>
      </div>
      <div class="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
        <span class="text-xs text-slate-400">${s.settled ? 'Settled' : 'Pending'}</span>
        <button onclick="settleSplit('${s.id}')" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md shadow-emerald-600/30 transition-all cursor-pointer">
          Settle ₹${s.myShare}
        </button>
      </div>
    </div>
  `).join('');
}

function settleSplit(splitId) {
  const split = appState.splits.find(s => s.id === splitId);
  if (!split) return;
  startPaymentFlow(split.title, "settle@senetinal", null, split.myShare);
}

// --- BANKS & CARDS ---
function renderBanks() {
  const container = document.getElementById('banks-container');
  if (!container) return;

  container.innerHTML = appState.banks.map(b => `
    <div class="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-blue-600/20 text-blue-400 flex items-center justify-center font-bold text-xs border border-blue-500/30">
          ${b.logo}
        </div>
        <div>
          <div class="flex items-center gap-1.5">
            <h3 class="text-sm font-bold text-white">${b.name}</h3>
            ${b.isPrimary ? '<span class="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-semibold">PRIMARY</span>' : ''}
          </div>
          <p class="text-xs text-slate-400">${b.acc}</p>
        </div>
      </div>
      <div class="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
        <div>
          <span class="text-[10px] text-slate-400">Balance</span>
          <div class="text-base font-black text-white font-heading">₹${b.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div>
        </div>
        <button onclick="openCheckBalanceModal()" class="px-3 py-1.5 rounded-xl bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 text-blue-400 text-xs font-semibold flex items-center gap-1 cursor-pointer">
          <i data-lucide="refresh-cw" class="w-3 h-3"></i>
          <span>Check Balance</span>
        </button>
      </div>
    </div>
  `).join('');
}

// --- NAVIGATION & TABS ---
function switchTab(tabName) {
  sound.playTap();
  ['home', 'bills', 'split', 'cards', 'history'].forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const navBtn = document.getElementById(`nav-btn-${t}`);
    if (el) el.classList.toggle('hidden', t !== tabName);
    if (navBtn) {
      if (t === tabName) {
        navBtn.className = "nav-item flex flex-col items-center gap-1 py-1 px-3 rounded-2xl text-blue-400 font-semibold cursor-pointer";
        navBtn.children[0].className = "p-1.5 rounded-xl bg-blue-600/20 text-blue-400 scale-110 shadow-lg shadow-blue-500/10";
      } else {
        navBtn.className = "nav-item flex flex-col items-center gap-1 py-1 px-3 rounded-2xl text-slate-400 hover:text-slate-200 cursor-pointer";
        navBtn.children[0].className = "p-1.5 rounded-xl";
      }
    }
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
  lucide.createIcons();
}

// --- PAYMENT FLOW LOGIC ---
function startPaymentFlow(name, upiId, avatar = null, prefillAmount = null) {
  sound.playTap();
  activePayment = { name, upiId, avatar };

  document.getElementById('pay-recipient-name').textContent = name;
  document.getElementById('pay-recipient-upi').textContent = upiId;

  const avatarContainer = document.getElementById('pay-avatar-container');
  if (avatarContainer) {
    avatarContainer.innerHTML = avatar
      ? `<img src="${avatar}" class="w-full h-full object-cover" />`
      : name.substring(0, 2).toUpperCase();
  }

  const amountInput = document.getElementById('pay-amount-input');
  if (amountInput) {
    amountInput.value = prefillAmount ? prefillAmount : '';
  }

  openModal('modal-payment');
}

function setPayAmount(val) {
  sound.playTap();
  const input = document.getElementById('pay-amount-input');
  if (input) input.value = val;
}

function handleProceedToPin(e) {
  e.preventDefault();
  const amt = parseFloat(document.getElementById('pay-amount-input').value);
  if (isNaN(amt) || amt <= 0) return;

  activePayment.amount = amt;
  activePayment.note = document.getElementById('pay-note-input').value || 'Payment via Senetinal Pay';
  activePayment.method = document.getElementById('pay-method-select').value;

  closeModal('modal-payment');

  // Setup PIN screen
  currentEnteredPin = '';
  updatePinDots();
  document.getElementById('pin-amount-display').textContent = `₹ ${amt.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
  document.getElementById('pin-recipient-display').textContent = activePayment.name;

  openModal('modal-upi-pin');
}

// --- PIN KEYPAD ---
function keypadPress(digit) {
  if (currentEnteredPin.length < 4) {
    sound.playPinDigit();
    currentEnteredPin += digit;
    updatePinDots();

    if (currentEnteredPin.length === 4) {
      setTimeout(verifyAndExecutePayment, 400);
    }
  }
}

function keypadDelete() {
  sound.playTap();
  currentEnteredPin = currentEnteredPin.slice(0, -1);
  updatePinDots();
}

function keypadBiometric() {
  sound.playPinDigit();
  currentEnteredPin = '1234';
  updatePinDots();
  setTimeout(verifyAndExecutePayment, 500);
}

function updatePinDots() {
  const dots = document.querySelectorAll('#pin-dots .pin-dot');
  dots.forEach((dot, idx) => {
    if (idx < currentEnteredPin.length) {
      dot.className = "pin-dot w-4 h-4 rounded-full bg-blue-500 scale-125 shadow-lg shadow-blue-500/50 transition-all";
    } else {
      dot.className = "pin-dot w-4 h-4 rounded-full bg-slate-800 border border-slate-700 transition-all";
    }
  });
}

function verifyAndExecutePayment() {
  closeModal('modal-upi-pin');

  const amt = activePayment.amount;

  // Deduct from wallet balance
  appState.walletBalance = Math.max(0, appState.walletBalance - amt);

  // Generate unique UTR
  const utr = `SENT${Math.floor(100000000000 + Math.random() * 900000000000)}`;

  const newTx = {
    id: `tx_${Date.now()}`,
    title: activePayment.name,
    upiId: activePayment.upiId,
    type: "debit",
    amount: amt,
    category: "Payment",
    timestamp: "Just now",
    method: activePayment.method.split(' ')[0],
    utr,
    note: activePayment.note
  };

  appState.transactions.unshift(newTx);
  currentTransactionReceipt = newTx;

  // Scratch card award for payments >= ₹50
  let awardedScratch = null;
  if (amt >= 50 && Math.random() > 0.2) {
    awardedScratch = {
      id: `r_${Date.now()}`,
      type: "cashback",
      title: "Cashback Reward",
      amount: Math.floor(Math.random() * 60) + 15,
      isScratched: false
    };
    appState.rewards.unshift(awardedScratch);
    currentScratchReward = awardedScratch;
  }

  saveState();
  renderAll();

  // Play ascending harmonic chime & blast confetti!
  sound.playSuccessChime();
  try {
    confetti({
      particleCount: 80,
      spread: 70,
      origin: { y: 0.6 },
      colors: ['#3b82f6', '#10b981', '#f59e0b', '#6366f1']
    });
  } catch (e) {}

  // Open Success Modal
  document.getElementById('success-amount-display').textContent = `₹ ${amt.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
  document.getElementById('success-recipient-display').textContent = activePayment.name;
  document.getElementById('success-method-display').textContent = activePayment.method;
  document.getElementById('success-utr-display').textContent = utr;

  const scratchBanner = document.getElementById('success-scratch-banner');
  if (scratchBanner) {
    scratchBanner.classList.toggle('hidden', !awardedScratch);
  }

  openModal('modal-success');
}

// --- SCRATCH CARD INTERACTION (HTML5 Canvas) ---
function openScratchModal(rewardId) {
  const reward = appState.rewards.find(r => r.id === rewardId);
  if (!reward) return;

  currentScratchReward = reward;

  document.getElementById('scratch-revealed-amount').textContent = `₹${reward.amount}`;
  document.getElementById('scratch-revealed-title').textContent = reward.title;

  const canvas = document.getElementById('scratch-canvas');
  const footer = document.getElementById('scratch-action-footer');

  if (reward.isScratched) {
    if (canvas) canvas.style.display = 'none';
    if (footer) footer.classList.remove('hidden');
    document.getElementById('scratch-modal-title').textContent = "Reward Claimed! 🎉";
  } else {
    document.getElementById('scratch-modal-title').textContent = "Scratch to Reveal Reward";
    if (canvas) {
      canvas.style.display = 'block';
      setupScratchCanvas(canvas, reward);
    }
    if (footer) footer.classList.add('hidden');
  }

  openModal('modal-scratch');
}

function openEarnedScratchCard() {
  closeModal('modal-success');
  if (currentScratchReward) {
    openScratchModal(currentScratchReward.id);
  }
}

function setupScratchCanvas(canvas, reward) {
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;

  // Holographic scratch coating
  const grad = ctx.createLinearGradient(0, 0, width, height);
  grad.addColorStop(0, '#64748b');
  grad.addColorStop(0.3, '#94a3b8');
  grad.addColorStop(0.5, '#cbd5e1');
  grad.addColorStop(0.7, '#94a3b8');
  grad.addColorStop(1, '#475569');

  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);

  ctx.font = 'bold 15px sans-serif';
  ctx.fillStyle = '#0f172a';
  ctx.textAlign = 'center';
  ctx.fillText('⚡ SENETINAL REWARDS', width / 2, height / 2 - 10);
  ctx.font = '12px sans-serif';
  ctx.fillStyle = '#1e293b';
  ctx.fillText('Scratch with mouse or finger', width / 2, height / 2 + 15);

  let isDrawing = false;
  let scratched = 0;

  function scratch(e) {
    if (!isDrawing) return;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const x = (clientX - rect.left) * (canvas.width / rect.width);
    const y = (clientY - rect.top) * (canvas.height / rect.height);

    ctx.globalCompositeOperation = 'destination-out';
    ctx.beginPath();
    ctx.arc(x, y, 24, 0, Math.PI * 2);
    ctx.fill();

    sound.playScratch();
    scratched += 80;

    if (scratched > (width * height * 0.35) && !reward.isScratched) {
      reward.isScratched = true;
      reward.scratchedAt = "Just now";
      appState.walletBalance += reward.amount;

      // Log credit transaction
      appState.transactions.unshift({
        id: `tx_r_${Date.now()}`,
        title: "Senetinal Cashback Reward",
        upiId: "rewards@senetinal",
        type: "credit",
        amount: reward.amount,
        category: "Rewards",
        timestamp: "Just now",
        method: "Senetinal Wallet",
        utr: `SENT${Math.floor(100000000000 + Math.random() * 900000000000)}`,
        note: "Cashback credited to wallet"
      });

      saveState();
      renderAll();

      sound.playSuccessChime();
      try {
        confetti({ particleCount: 50, spread: 60, origin: { y: 0.5 } });
      } catch (err) {}

      document.getElementById('scratch-action-footer').classList.remove('hidden');
      document.getElementById('scratch-modal-title').textContent = "Congratulations! 🎉";
    }
  }

  canvas.onmousedown = (e) => { isDrawing = true; scratch(e); };
  canvas.onmousemove = scratch;
  window.onmouseup = () => { isDrawing = false; };

  canvas.ontouchstart = (e) => { isDrawing = true; scratch(e); };
  canvas.ontouchmove = scratch;
  window.ontouchend = () => { isDrawing = false; };
}

// --- CHECK BALANCE FLOW ---
let checkBalancePin = '';
function openCheckBalanceModal() {
  sound.playTap();
  checkBalancePin = '';
  updateCheckBalanceDots();
  document.getElementById('check-balance-pin-view').classList.remove('hidden');
  document.getElementById('check-balance-result-view').classList.add('hidden');
  openModal('modal-check-balance');
}

function checkBalanceKeyPress(digit) {
  if (checkBalancePin.length < 4) {
    sound.playPinDigit();
    checkBalancePin += digit;
    updateCheckBalanceDots();
    if (checkBalancePin.length === 4) {
      setTimeout(() => {
        sound.playSuccessChime();
        document.getElementById('check-balance-pin-view').classList.add('hidden');
        document.getElementById('check-balance-result-view').classList.remove('hidden');
      }, 500);
    }
  }
}

function checkBalanceDelete() {
  sound.playTap();
  checkBalancePin = checkBalancePin.slice(0, -1);
  updateCheckBalanceDots();
}

function updateCheckBalanceDots() {
  const dots = document.querySelectorAll('#check-balance-dots div');
  dots.forEach((dot, idx) => {
    dot.className = idx < checkBalancePin.length
      ? "w-3.5 h-3.5 rounded-full bg-blue-500 scale-125 shadow-md shadow-blue-500/50"
      : "w-3.5 h-3.5 rounded-full bg-slate-800 border border-slate-700";
  });
}

// --- RECEIPT MODAL ---
function openReceiptModal(txId) {
  const tx = appState.transactions.find(t => t.id === txId);
  if (!tx) return;
  currentTransactionReceipt = tx;
  populateAndOpenReceipt(tx);
}

function viewCurrentReceipt() {
  closeModal('modal-success');
  if (currentTransactionReceipt) {
    populateAndOpenReceipt(currentTransactionReceipt);
  }
}

function populateAndOpenReceipt(tx) {
  document.getElementById('receipt-amount-display').textContent = `₹ ${tx.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
  document.getElementById('receipt-recipient-display').textContent = tx.title;
  document.getElementById('receipt-method-display').textContent = tx.method;
  document.getElementById('receipt-utr-display').textContent = tx.utr;
  document.getElementById('receipt-date-display').textContent = tx.timestamp;
  openModal('modal-receipt');
}

function shareReceipt() {
  if (currentTransactionReceipt) {
    navigator.clipboard?.writeText(`Senetinal Pay Receipt: Paid ₹${currentTransactionReceipt.amount} to ${currentTransactionReceipt.title}. UTR: ${currentTransactionReceipt.utr}`);
    alert("Receipt details copied to clipboard!");
  }
}

// --- QUICK ACTIONS ---
function triggerSelfTransfer() {
  startPaymentFlow("My HDFC Bank A/C", "aarav.self@hdfcbank", null, 1000);
}

function openQuickInputModal(type) {
  let promptText = "Enter Mobile Number:";
  if (type === 'upi') promptText = "Enter UPI ID (e.g. name@oksbi):";
  if (type === 'bank') promptText = "Enter Account Number & IFSC:";

  const input = prompt(promptText);
  if (!input) return;

  const upiId = type === 'upi' ? input : `${input.replace(/\s+/g, '')}@senetinal`;
  startPaymentFlow(input, upiId);
}

function quickRecharge(plan) {
  startPaymentFlow(plan, "recharge@senetinal", null, 299);
}

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth' });
}

// --- QR MODAL ---
function openQrModal(tab = 'scan') {
  sound.playTap();
  switchQrTab(tab);
  openModal('modal-qr');
}

function switchQrTab(tab) {
  const scanView = document.getElementById('qr-view-scan');
  const myQrView = document.getElementById('qr-view-myqr');
  const scanBtn = document.getElementById('qr-tab-scan-btn');
  const myQrBtn = document.getElementById('qr-tab-myqr-btn');

  if (tab === 'scan') {
    scanView.classList.remove('hidden');
    myQrView.classList.add('hidden');
    scanBtn.className = "flex-1 py-1.5 rounded-xl text-xs font-semibold bg-blue-600 text-white cursor-pointer";
    myQrBtn.className = "flex-1 py-1.5 rounded-xl text-xs font-semibold text-slate-400 hover:text-white cursor-pointer";
  } else {
    scanView.classList.add('hidden');
    myQrView.classList.remove('hidden');
    scanBtn.className = "flex-1 py-1.5 rounded-xl text-xs font-semibold text-slate-400 hover:text-white cursor-pointer";
    myQrBtn.className = "flex-1 py-1.5 rounded-xl text-xs font-semibold bg-blue-600 text-white cursor-pointer";
  }
}

function simulateScan(name, upiId) {
  closeModal('modal-qr');
  startPaymentFlow(name, upiId);
}

function copyUpiId() {
  navigator.clipboard?.writeText('aarav@senetinal');
  alert("UPI ID copied: aarav@senetinal");
}

// --- VIRTUAL CARDS ---
let isCardFrozen = false;
let isCvvVisible = false;

function toggleCardFreeze() {
  sound.playTap();
  isCardFrozen = !isCardFrozen;
  document.getElementById('card-frozen-overlay').classList.toggle('hidden', !isCardFrozen);
  document.getElementById('freeze-btn-text').textContent = isCardFrozen ? 'Unfreeze Card' : 'Freeze Card';
}

function toggleCvvVisibility() {
  sound.playTap();
  isCvvVisible = !isCvvVisible;
  document.getElementById('card-cvv-display').textContent = isCvvVisible ? '782' : '•••';
  document.getElementById('cvv-btn-text').textContent = isCvvVisible ? 'Hide CVV' : 'View CVV';
}

// --- SPLIT BILLS MODAL ---
function openCreateSplitModal() {
  const title = prompt("Enter Split Title (e.g. Dinner, Goa Trip):");
  if (!title) return;
  const amt = parseFloat(prompt("Enter Total Amount (₹):") || "0");
  if (isNaN(amt) || amt <= 0) return;

  const peopleCount = parseInt(prompt("How many people are splitting? (including you):") || "3", 10);
  const share = Math.round(amt / peopleCount);

  appState.splits.unshift({
    id: `s_${Date.now()}`,
    title,
    totalAmount: amt,
    myShare: share,
    members: ["Aarav (You)", `Friend 1`, `Friend 2`],
    settled: false
  });
  saveState();
  renderSplits();
  lucide.createIcons();
}

// --- STATEMENT CSV EXPORT ---
function exportStatementCSV() {
  const csvContent = "data:text/csv;charset=utf-8," +
    ["Date,Title,UPI ID,Type,Amount,Method,UTR", ...appState.transactions.map(t =>
      `"${t.timestamp}","${t.title}","${t.upiId}","${t.type}",${t.amount},"${t.method}","${t.utr}"`
    )].join("\n");

  const link = document.createElement("a");
  link.setAttribute("href", encodeURI(csvContent));
  link.setAttribute("download", `senetinalpay_statement_${Date.now()}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function filterTransactions(filter) {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.className = "filter-btn px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap bg-slate-800 text-slate-400 hover:text-white cursor-pointer";
  });
  if (event && event.target) {
    event.target.className = "filter-btn active px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap bg-blue-600 text-white cursor-pointer";
  }
  renderTransactions(filter);
  lucide.createIcons();
}

// --- PROFILE & SETTINGS ---
function openProfileModal() {
  sound.playTap();
  openModal('modal-profile');
}

function openNotificationModal() {
  sound.playTap();
  openModal('modal-notif');
}

function openReferralModal() {
  prompt("Share your referral link with friends to earn ₹101:", "https://senetinalpay.app/invite/aarav101");
}

function markAllNotificationsRead() {
  const badge = document.getElementById('notif-badge');
  if (badge) badge.style.display = 'none';
  alert("All notifications marked as read!");
}

function toggleSound() {
  sound.enabled = !sound.enabled;
  document.getElementById('sound-toggle-btn').textContent = sound.enabled ? 'ON' : 'OFF';
  document.getElementById('sound-toggle-btn').className = sound.enabled
    ? 'px-3 py-1 rounded-xl bg-blue-600 text-xs text-white font-semibold cursor-pointer'
    : 'px-3 py-1 rounded-xl bg-slate-700 text-xs text-slate-300 font-semibold cursor-pointer';
}

function resetDemoData() {
  if (confirm("Reset all balances, scratch cards and demo transactions to default?")) {
    localStorage.removeItem('senetinalpay_state');
    appState = JSON.parse(JSON.stringify(DEFAULT_STATE));
    renderAll();
    closeModal('modal-profile');
    sound.playSuccessChime();
  }
}

// --- SEARCH ---
function handleSearch(query) {
  renderPeople(query);
  lucide.createIcons();
}

// --- DEVICE FRAME SIMULATOR TOGGLE ---
function toggleDeviceFrame() {
  const wrapper = document.getElementById('device-wrapper');
  appState.deviceFrame = !appState.deviceFrame;
  wrapper.classList.toggle('device-frame-active', appState.deviceFrame);
  saveState();
}

// --- THEME TOGGLE ---
function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.classList.toggle('dark');
  const icon = document.getElementById('theme-toggle-icon');
  if (icon) {
    icon.setAttribute('data-lucide', isDark ? 'sun' : 'moon');
    lucide.createIcons();
  }
}

// --- GENERIC MODAL CONTROLS ---
function openModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) {
    el.classList.remove('hidden');
    lucide.createIcons();
  }
}

function closeModal(modalId) {
  const el = document.getElementById(modalId);
  if (el) el.classList.add('hidden');
}
