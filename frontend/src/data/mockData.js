/** Sandbox seed data for the React demo. Not bank accounts. */

export const INITIAL_USER = {
  name: "Aarav Sharma",
  upiId: "aarav@senitenial",
  phone: "+91 98765 43210",
  email: "aarav.sharma@example.com",
  avatar: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&q=80&w=150",
  currency: "₹",
  walletBalance: 24850.0,
  securityScore: "99.9",
  kycStatus: "KYC Verified",
  city: "Bengaluru",
  location: { lat: 12.9716, lon: 77.5946 },
  deviceId: "dev-aarav-1001"
};

export const DEMO_PROFILES = [
  {
    id: "aarav",
    name: "Aarav Sharma",
    upiId: "aarav@senitenial",
    city: "Bengaluru",
    location: { lat: 12.9716, lon: 77.5946 },
    deviceId: "dev-aarav-1001",
    walletBalance: 24850.0
  },
  {
    id: "priya",
    name: "Priya Mehra",
    upiId: "priya@senitenial",
    city: "Delhi",
    location: { lat: 28.6139, lon: 77.209 },
    deviceId: "dev-priya-1002",
    walletBalance: 18240.0
  }
];

export const INITIAL_BANKS = [
  {
    id: "b-sbi",
    bankName: "State Bank of India",
    accountNumber: "•••• 4821",
    accountType: "Savings Account",
    balance: 58320.0,
    ifsc: "SBIN0001892",
    isPrimary: true,
    color: "from-blue-600 to-indigo-800",
    logoText: "SBI"
  },
  {
    id: "b-hdfc",
    bankName: "HDFC Bank",
    accountNumber: "•••• 9012",
    accountType: "Savings Account",
    balance: 112400.0,
    ifsc: "HDFC0001892",
    isPrimary: false,
    color: "from-red-600 to-rose-800",
    logoText: "HDFC"
  },
  {
    id: "b-vault",
    bankName: "Senitenial Reserve Vault",
    accountNumber: "•••• 7733",
    accountType: "Savings Account",
    balance: 250000.0,
    ifsc: "SENT0001892",
    isPrimary: false,
    color: "from-emerald-600 to-teal-800",
    logoText: "VAULT"
  }
];

export const INITIAL_CARDS = [
  {
    id: "card-1",
    cardNumber: "4532 •••• •••• 4298",
    name: "Aarav Sharma",
    expiry: "09/28",
    cvv: "782",
    variant: "Metal Black Edition",
    type: "VISA",
    isFrozen: false
  }
];

export const INITIAL_CONTACTS = [
  { id: "c1", name: "Priya Patel", upiId: "priya.p@oksbi", phone: "+91 98234 56781", avatar: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&q=80&w=150", recentAmount: 850, verified: true },
  { id: "c2", name: "Rohan Verma", upiId: "rohanv@senetinal", phone: "+91 97112 34567", avatar: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&q=80&w=150", recentAmount: 2400, verified: true },
  { id: "c3", name: "Ananya Iyer", upiId: "ananya.iyer@okhdfcbank", phone: "+91 96543 21098", avatar: "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&q=80&w=150", recentAmount: 500, verified: true },
  { id: "c4", name: "Devendra Singh", upiId: "dev.singh@senetinal", phone: "+91 99887 76655", avatar: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&q=80&w=150", recentAmount: 1200, verified: true },
  { id: "c5", name: "Sneha Roy", upiId: "sneha.roy@okaxis", phone: "+91 91234 87654", avatar: "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&q=80&w=150", recentAmount: 1500, verified: true },
  { id: "c6", name: "Vikram Malhotra", upiId: "vikram.m@paytm", phone: "+91 93456 12789", avatar: "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?auto=format&fit=crop&q=80&w=150", recentAmount: 320, verified: false }
];

export const INITIAL_MERCHANTS = [
  { id: "m1", name: "Zomato", category: "Food Delivery", upiId: "zomato@icici", cashbackOffer: "Flat ₹50 cashback", icon: "Utensils", bg: "text-red-400 bg-red-500/10 border-red-500/20" },
  { id: "m2", name: "Swiggy", category: "Food & Instamart", upiId: "swiggy@hdfcbank", cashbackOffer: "Up to ₹100 scratch card", icon: "ShoppingBag", bg: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
  { id: "m3", name: "Amazon India", category: "Online Shopping", upiId: "amazonpay@apl", cashbackOffer: "5% Sentinel Cashback", icon: "Package", bg: "text-amber-400 bg-amber-500/10 border-amber-500/20" },
  { id: "m4", name: "Uber", category: "Rides & Cabs", upiId: "uber.india@axisbank", cashbackOffer: "₹40 off 1st ride", icon: "Car", bg: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
  { id: "m5", name: "Netflix India", category: "Entertainment", upiId: "netflix@citi", cashbackOffer: "Auto-pay reward active", icon: "Tv", bg: "text-rose-400 bg-rose-500/10 border-rose-500/20" },
  { id: "m6", name: "Starbucks", category: "Coffee & Dining", upiId: "starbucks@yesbank", cashbackOffer: "Free upgrade scratch reward", icon: "Coffee", bg: "text-amber-500 bg-amber-500/10 border-amber-500/20" }
];

export const INITIAL_BILLS = [
  { id: "b1", billerName: "Tata Power Mumbai", category: "Electricity", consumerNumber: "900234110", amountDue: 1840.0, dueDate: "2026-09-28", status: "Due Soon", icon: "zap" },
  { id: "b2", billerName: "Jio Fiber Ultra", category: "Broadband", consumerNumber: "022-4912984", amountDue: 1179.0, dueDate: "2026-10-02", status: "Upcoming", icon: "wifi" },
  { id: "b3", billerName: "Airtel 5G Postpaid", category: "Mobile", consumerNumber: "9876543210", amountDue: 699.0, dueDate: "2026-09-30", status: "Due Soon", icon: "smartphone" },
  { id: "b4", billerName: "Mahanagar Gas (MGL)", category: "Gas", consumerNumber: "MG-889123", amountDue: 740.0, dueDate: "2026-10-05", status: "Upcoming", icon: "flame" }
];

export const INITIAL_REWARDS = [
  { id: "r1", type: "cashback", title: "Cashback Reward", amount: 65, description: "Demo scratch card", isScratched: false, expiryDate: "Valid for 7 days", code: "DEMO-R1" },
  { id: "r2", type: "cashback", title: "Weekend Bonus", amount: 40, description: "Demo scratch card", isScratched: false, expiryDate: "Valid for 7 days", code: "DEMO-R2" },
  { id: "r3", type: "cashback", title: "Cashback Won", amount: 45, description: "Already claimed demo reward", isScratched: true, scratchedAt: "Yesterday", expiryDate: "Valid for 7 days", code: "CLAIMED" }
];

export const INITIAL_TRANSACTIONS = [
  { id: "tx1", title: "Priya Patel", upiId: "priya.p@oksbi", type: "debit", amount: 850.0, category: "Food & Dining", timestamp: "Today, 11:42 AM", status: "Sandbox", method: "SBI •••• 4821", utr: "DEMO-tx1", note: "Brunch split 🥞" },
  { id: "tx2", title: "Rohan Verma", upiId: "rohanv@senetinal", type: "credit", amount: 2400.0, category: "Transfer", timestamp: "Yesterday, 8:15 PM", status: "Sandbox", method: "Senitenial Wallet", utr: "DEMO-tx2", note: "Goa flight ticket share" },
  { id: "tx3", title: "Tata Power Electricity", upiId: "tatapower@billpay", type: "debit", amount: 1640.0, category: "Utility Bills", timestamp: "21 Sep 2026", status: "Sandbox", method: "HDFC •••• 9012", utr: "DEMO-tx3", note: "Bill Payment - Consumer #900234110" },
  { id: "tx4", title: "Senitenial Scratch Cashback", upiId: "rewards@senitenial", type: "credit", amount: 45.0, category: "Rewards", timestamp: "20 Sep 2026", status: "Sandbox", method: "Senitenial Wallet", utr: "DEMO-tx4", note: "Generated demo cashback" },
  { id: "tx5", title: "Starbucks Reserve", upiId: "starbucks@yesbank", type: "debit", amount: 490.0, category: "Coffee & Dining", timestamp: "19 Sep 2026", status: "Sandbox", method: "Metal Black •••• 4298", utr: "DEMO-tx5", note: "Caramel Macchiato" }
];

export const INITIAL_SPLIT_GROUPS = [
  { id: "s1", title: "Goa Beach Villa Weekend", category: "Travel", totalAmount: 14200, myShare: 3550, members: ["Aarav (You)", "Priya", "Rohan", "Sneha"], settled: false },
  { id: "s2", title: "Apartment 402 Wifi & Grocery", category: "Home", totalAmount: 4800, myShare: 1600, members: ["Aarav (You)", "Devendra", "Ananya"], settled: false }
];

export const INITIAL_SPLITS = INITIAL_SPLIT_GROUPS.map((item) => ({
  ...item,
  members: [...item.members]
}));

export const POPULAR_BANKS_LIST = [
  "State Bank of India",
  "HDFC Bank",
  "ICICI Bank",
  "Axis Bank",
  "Kotak Mahindra Bank",
  "Punjab National Bank",
  "Bank of Baroda",
  "Yes Bank",
  "IDFC First Bank",
  "Union Bank of India"
];
