// Reproducible, original exact-probability strategy data builder.
// No vendor game code or strategy tables are used.
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
#ifndef CAB_FAMILY
#define CAB_FAMILY 0
#endif
constexpr int ND = CAB_FAMILY==2 ? 53 : 52;
constexpr int NC = CAB_FAMILY==0 ? 14 : 20, NM = 12;
constexpr uint32_t TOTAL = ND==53 ? 2869685 : 2598960;
int PAY[NC]{}, MUL[NC]{}, NHANDS=10;
constexpr int MVAL[NM] = {1,2,3,4,5,6,7,8,9,10,11,12};
std::vector<int> ALLOWED;
uint32_t CB[ND+1][6]{};
int PC[32]{};
uint32_t DEN[32]{};
struct Row {
  uint32_t q[NM];
  uint32_t pay;
};
struct Hand {
  uint8_t cards[5], weight, pad[2];
  Row row[32];
};
static_assert(sizeof(Row) == 52 && sizeof(Hand) == 1672, "cache layout");
struct Table {
  std::array<std::vector<uint32_t>, 5> a;
};

auto now() { return std::chrono::steady_clock::now(); }
double elapsed(std::chrono::steady_clock::time_point t) {
  return std::chrono::duration<double>(now() - t).count();
}
void init() {
  for (int n = 0; n <= ND; n++) {
    CB[n][0] = 1;
    for (int k = 1; k <= 5; k++)
      CB[n][k] = (n ? CB[n - 1][k - 1] : 0) + (n ? CB[n - 1][k] : 0);
  }
  for (int m = 0; m < 32; m++) {
    PC[m] = __builtin_popcount(unsigned(m));
    DEN[m] = CB[ND-5][5 - PC[m]];
  }
}
int standard_category(const uint8_t *h) {
  int count[13] = {}, nr = 0, ranks = 0, four = -1, three = -1, pairs = 0,
      pair = -1;
  bool flush = true;
  for (int i = 0; i < 5; i++) {
    int r = h[i] % 13;
    count[r]++;
    ranks |= 1 << r;
    flush &= (h[i] / 13 == h[0] / 13);
  }
  for (int r = 0; r < 13; r++)
    if (count[r]) {
      nr++;
      if (count[r] == 4)
        four = r;
      if (count[r] == 3)
        three = r;
      if (count[r] == 2) {
        pairs++;
        pair = r;
      }
    }
  bool straight = false;
  if (nr == 5) {
    for (int lo = 0; lo < 9; lo++)
      if (ranks == (31 << lo))
        straight = true;
    if (ranks == 0x100f)
      straight = true;
  }
  if (flush && straight)
    return ranks == 0x1f00 ? 0 : 1;
  if (four >= 0) {
    int kick = 0;
    while (count[kick] != 1)
      kick++;
    if (four == 12)
      return kick <= 2 ? 2 : 4;
    if (four <= 2)
      return (kick == 12 || kick <= 2) ? 3 : 5;
    return 6;
  }
  if (three >= 0 && pairs)
    return 7;
  if (flush)
    return 8;
  if (straight)
    return 9;
  if (three >= 0)
    return 10;
  if (pairs == 2)
    return 11;
  if (pairs == 1 && pair >= 9)
    return 12;
  return 13;
}
int category(const uint8_t *h) {
  if constexpr(CAB_FAMILY==0) return standard_category(h);
  int ct[13]={}, wild=0, nat=0, mask=0, distinct=0, maxct=0, pairs=0, high=-1;
  int suit=-1; bool flush=true;
  for(int i=0;i<5;i++) {
    int c=h[i],r=c%13;
    if(c==52 || (CAB_FAMILY==1 && r==0)) {wild++;continue;}
    nat++;ct[r]++;mask|=1<<r;
    if(suit<0)suit=c/13;else flush &= suit==c/13;
  }
  for(int r=0;r<13;r++)if(ct[r]) {
    distinct++;maxct=std::max(maxct,ct[r]);high=r;
    if(ct[r]==2)pairs++;
  }
  bool unique=distinct==nat, straight=false;
  if(unique){
    for(int lo=0;lo<9;lo++)if((mask & ~(31<<lo))==0)straight=true;
    if((mask & ~0x100f)==0)straight=true;
  }
  if(!wild && flush && mask==0x1f00)return 0;
  if(CAB_FAMILY==1 && wild==4)return ct[12] ? 16 : 15;
  if(wild && flush && unique && (mask & ~0x1f00)==0)return 14;
  if(distinct==1 && maxct+wild==5)return high==12 ? 17 : high<=3 ? 18 : 19;
  if(flush && straight)return 1;
  if(maxct+wild>=4)return 6;
  if(distinct==2 && maxct+wild>=3)return 7;
  if(flush)return 8;
  if(straight)return 9;
  if(maxct+wild>=3)return 10;
  if(CAB_FAMILY==2){
    if(pairs==2)return 11;
    for(int r=11;r<13;r++)if(ct[r]+wild>=2)return 12;
  }
  return 13;
}
uint64_t subset_body_size() {
  uint64_t size=0;
  for(int k=0;k<5;k++)size+=uint64_t(CB[ND][k])*NC*(k<2?4:k<4?2:1);
  return size;
}
void wr32(std::ostream &o, uint32_t v) {
  for (int i = 0; i < 4; i++)
    o.put(char((v >> (8 * i)) & 255));
}
void wr64(std::ostream &o, uint64_t v) {
  for (int i = 0; i < 8; i++)
    o.put(char((v >> (8 * i)) & 255));
}
uint32_t rd32(std::istream &in) {
  uint32_t v = 0;
  for (int i = 0; i < 4; i++) {
    int c = in.get();
    if (c < 0)
      throw std::runtime_error("truncated file");
    v |= uint32_t(c) << (i * 8);
  }
  return v;
}
uint64_t rd64(std::istream &in) {
  uint64_t v = 0;
  for (int i = 0; i < 8; i++) {
    int c = in.get();
    if (c < 0)
      throw std::runtime_error("truncated file");
    v |= uint64_t(c) << (i * 8);
  }
  return v;
}
void alloc(Table &t) {
  for (int k = 0; k < 5; k++)
    t.a[k].resize(size_t(CB[ND][k]) * NC);
}
uint32_t rank_subset(const uint8_t *h, int mask) {
  uint32_t r = 0;
  int k = 0;
  for (int i = 0; i < 5; i++)
    if (mask & (1 << i))
      r += CB[h[i]][++k];
  return r;
}
void write_subset(const fs::path &p, const Table &t) {
  std::ofstream o(p, std::ios::binary);
  o.write("UXSUB01\0", 8);
  wr32(o, 1);
  wr32(o, 64);
  wr32(o, NC);
  wr32(o, ND);
  wr32(o, 4);
  wr32(o, 0);
  wr64(o, 64);
  wr64(o, subset_body_size());
  wr64(o, 0);
  wr64(o, 0);
  for (int k = 0; k < 5; k++) {
    int width = k < 2 ? 4 : k < 4 ? 2 : 1;
    for (uint32_t n : t.a[k]) {
      if (width < 4 && n >= (1u << (width * 8)))
        throw std::runtime_error("packed count overflow");
      for (int j = 0; j < width; j++)
        o.put(char((n >> (8 * j)) & 255));
    }
  }
  if (!o)
    throw std::runtime_error("could not write subset table");
}
Table read_subset(const fs::path &p) {
  std::ifstream in(p, std::ios::binary);
  char magic[8];
  in.read(magic, 8);
  if (std::memcmp(magic, "UXSUB01\0", 8) || rd32(in) != 1 || rd32(in) != 64 ||
      rd32(in) != NC || rd32(in) != ND || rd32(in) != 4 || rd32(in) != 0 ||
      rd64(in) != 64 || rd64(in) != subset_body_size() || rd64(in) != 0 || rd64(in) != 0)
    throw std::runtime_error("bad subset header");
  Table t;
  alloc(t);
  for (int k = 0; k < 5; k++) {
    int width = k < 2 ? 4 : k < 4 ? 2 : 1;
    for (auto &n : t.a[k]) {
      n = 0;
      for (int j = 0; j < width; j++) {
        int c = in.get();
        if (c < 0)
          throw std::runtime_error("truncated subsets");
        n |= uint32_t(c) << (8 * j);
      }
    }
  }
  if (in.peek() != EOF)
    throw std::runtime_error("extra subset data");
  return t;
}
Table generate_subset(const fs::path &p) {
  auto tm = now();
  Table t;
  alloc(t);
  uint8_t h[5];
  uint32_t seen = 0;
  for (h[4] = 4; h[4] < ND; h[4]++)
    for (h[3] = 3; h[3] < h[4]; h[3]++)
      for (h[2] = 2; h[2] < h[3]; h[2]++)
        for (h[1] = 1; h[1] < h[2]; h[1]++)
          for (h[0] = 0; h[0] < h[1]; h[0]++) {
            int c = category(h);
            uint32_t ix[32] = {};
            for (int m = 1; m < 31; m++) {
              int b = 31 - __builtin_clz(unsigned(m));
              ix[m] = ix[m ^ (1 << b)] + CB[h[b]][PC[m]];
            }
            for (int m = 0; m < 31; m++)
              t.a[PC[m]][size_t(ix[m]) * NC + c]++;
            seen++;
          }
  if (seen != TOTAL)
    throw std::runtime_error("terminal hand count mismatch");
  write_subset(p, t);
  std::cout << "subsets hands=" << seen << " seconds=" << elapsed(tm) << "\n"
            << std::flush;
  return t;
}
void histogram(const Table &t, const uint8_t *h, uint32_t out[32][NC]) {
  for (int m = 0; m < 31; m++)
    std::memcpy(out[m], &t.a[PC[m]][size_t(rank_subset(h, m)) * NC], NC * 4);
  std::fill(out[31], out[31] + NC, 0);
  out[31][category(h)] = 1;
  for (int b = 0; b < 5; b++)
    for (int m = 0; m < 32; m++)
      if (!(m & (1 << b)))
        for (int c = 0; c < NC; c++) {
          if (out[m][c] < out[m | (1 << b)][c])
            throw std::runtime_error("Mobius negative count");
          out[m][c] -= out[m | (1 << b)][c];
        }
  for (int m = 0; m < 32; m++) {
    uint32_t sum = 0;
    for (int c = 0; c < NC; c++)
      sum += out[m][c];
    if (sum != DEN[m])
      throw std::runtime_error("Mobius denominator mismatch");
  }
}
std::vector<Hand> generate_hands(const fs::path &p, const Table &t) {
  auto tm = now();
  std::vector<Hand> hs;
  hs.reserve(134459);
  std::vector<uint8_t> marked(TOTAL);
  uint8_t h[5];
  uint32_t seen = 0, orbit_total = 0;
  for (h[4] = 4; h[4] < ND; h[4]++)
    for (h[3] = 3; h[3] < h[4]; h[3]++)
      for (h[2] = 2; h[2] < h[3]; h[2]++)
        for (h[1] = 1; h[1] < h[2]; h[1]++)
          for (h[0] = 0; h[0] < h[1]; h[0]++) {
            uint32_t id = rank_subset(h, 31);
            if (marked[id])
              continue;
            int perm[4] = {0, 1, 2, 3};
            int weight = 0;
            do {
              uint8_t x[5];
              for (int i = 0; i < 5; i++)
                x[i] = uint8_t(h[i]==52 ? 52 : 13 * perm[h[i] / 13] + h[i] % 13);
              std::sort(x, x + 5);
              uint32_t j = rank_subset(x, 31);
              if (!marked[j]) {
                marked[j] = 1;
                weight++;
              }
            } while (std::next_permutation(perm, perm + 4));
            Hand rec{};
            std::copy(h, h + 5, rec.cards);
            rec.weight = uint8_t(weight);
            uint32_t hist[32][NC];
            histogram(t, h, hist);
            for (int m = 0; m < 32; m++)
              for (int c = 0; c < NC; c++) {
                int k = std::find(MVAL, MVAL + NM, MUL[c]) - MVAL;
                rec.row[m].q[k] += hist[m][c];
                rec.row[m].pay += hist[m][c] * PAY[c];
              }
            hs.push_back(rec);
            seen++;
            orbit_total += weight;
          }
  if ((ND==52 && seen != 134459) || orbit_total != TOTAL)
    throw std::runtime_error("canonical hand count mismatch");
  std::ofstream o(p, std::ios::binary);
  o.write("UXCAN01\0", 8);
  wr32(o, 1);
  wr32(o, sizeof(Hand));
  wr32(o, hs.size());
  wr32(o, 0);
  for (int i = 0; i < 5; i++)
    wr64(o, 0);
  o.write(reinterpret_cast<const char *>(hs.data()), hs.size() * sizeof(Hand));
  if (!o)
    throw std::runtime_error("cache write failed");
  std::cout << "canonical hands=" << seen << " orbit_weight=" << orbit_total
            << " seconds=" << elapsed(tm) << "\n"
            << std::flush;
  return hs;
}
std::vector<Hand> read_hands(const fs::path &p) {
  std::ifstream in(p, std::ios::binary);
  char m[8];
  in.read(m, 8);
  uint32_t ver=rd32(in), record_size=rd32(in), records=rd32(in), reserved=rd32(in);
  if (std::memcmp(m, "UXCAN01\0", 8) || ver != 1 ||
      record_size != sizeof(Hand) || records<134459 || records>200000 || reserved != 0)
    throw std::runtime_error("bad canonical cache");
  for (int i = 0; i < 5; i++)
    if (rd64(in) != 0)
      throw std::runtime_error("bad cache reserved header");
  std::vector<Hand> h(records);
  in.read(reinterpret_cast<char *>(h.data()), h.size() * sizeof(Hand));
  if (!in || in.peek() != EOF)
    throw std::runtime_error("bad cache length");
  return h;
}
std::vector<int> states() {
  std::array<bool, 121> s{};
  s[0] = true;
  for (int n = 0; n < NHANDS; n++) {
    std::array<bool, 121> t{};
    for (int a = 0; a <= 120; a++)
      if (s[a])
        for (int m : ALLOWED)
          if (a + m <= 120)
            t[a + m] = true;
    s = t;
  }
  std::vector<int> r;
  for (int a = 0; a <= 120; a++)
    if (s[a])
      r.push_back(a);
  if (r.empty() || r.front()!=NHANDS || r.back()>12*NHANDS)
    throw std::runtime_error("states mismatch");
  return r;
}
void distribution(const Row &row, int mask, double *result) {
  double a[121] = {}, b[121];
  a[0] = 1;
  double q[NM];
  for (int j = 0; j < NM; j++)
    q[j] = double(row.q[j]) / DEN[mask];
  for (int n = 0; n < NHANDS; n++) {
    std::fill(b, b + 121, 0.0);
    for (int j = 0; j < NM; j++)
      if (q[j] != 0.0) {
        int m = MVAL[j];
        for (int s = n; s <= 12 * n; s++)
          b[s + m] += a[s] * q[j];
      }
    std::copy(b, b + 121, a);
  }
  std::copy(a, a + 121, result);
}
struct Work {
  std::array<long double, 121> sum{};
  uint64_t convolutions = 0, changes = 0;
  double min_gap = std::numeric_limits<double>::infinity();
};
struct Solver {
  const std::vector<Hand> &hands;
  std::vector<int> ss;
  int threads;
  std::vector<uint8_t> policy;
  double tie = 1e-9;
  Solver(const std::vector<Hand> &h, int nt)
      : hands(h), ss(states()), threads(nt), policy(h.size() * ss.size(), 255) {
  }
  Work chunk(const std::array<double, 121> &v, double slope, double emin,
             double emax, size_t begin, size_t end, bool update) {
    Work w;
    for (size_t hi = begin; hi < end; hi++) {
      const Hand &h = hands[hi];
      double r[32], line_intercept[32], linearbest[121] = {};
      bool candidate[32] = {};
      double cont[32] = {};
      for (int m = 0; m < 32; m++) {
        r[m] = 5.0 * h.row[m].pay / DEN[m];
        double em = 0;
        for (int j = 0; j < NM; j++)
          em += double(h.row[m].q[j]) * MVAL[j] / DEN[m];
        line_intercept[m] = NHANDS * slope * em;
      }
      for (int s : ss) {
        double best = -1e300;
        for (int m = 0; m < 32; m++)
          best = std::max(best, s * r[m] + line_intercept[m]);
        linearbest[s] = best;
      }
      for (int m = 0; m < 32; m++)
        for (int s : ss)
          if (s * r[m] + line_intercept[m] + emax >=
              linearbest[s] + emin - 1e-10) {
            candidate[m] = true;
            break;
          }
      for (int m = 0; m < 32; m++)
        if (candidate[m]) {
          double q[121];
          distribution(h.row[m], m, q);
          for (int s : ss)
            cont[m] += q[s] * v[s];
          w.convolutions++;
        }
      for (size_t si = 0; si < ss.size(); si++) {
        int s = ss[si], bestm = -1;
        double best = -1e300, runner = -1e300;
        for (int m = 0; m < 32; m++)
          if (candidate[m]) {
            double x = s * r[m] + cont[m];
            if (x > best + tie || (std::abs(x - best) <= tie &&
                                   (bestm < 0 || PC[m] > PC[bestm] ||
                                    (PC[m] == PC[bestm] && m < bestm)))) {
              runner = best;
              best = x;
              bestm = m;
            } else
              runner = std::max(runner, x);
          }
        // The Bellman operator uses the numerical maximum independently of
        // policy tie-breaking.
        double truebest = best;
        for (int m = 0; m < 32; m++)
          if (candidate[m])
            truebest = std::max(truebest, s * r[m] + cont[m]);
        w.sum[s] += static_cast<long double>(h.weight) * truebest;
        double gap = best - runner;
        if (gap > tie)
          w.min_gap = std::min(w.min_gap, gap);
        if (update) {
          size_t ix = hi * ss.size() + si;
          if (policy[ix] != bestm) {
            w.changes++;
            policy[ix] = uint8_t(bestm);
          }
        }
      }
    }
    return w;
  }
  Work apply(const std::array<double, 121> &v, bool update = true,
             size_t limit = 0) {
    double a = (v[ss.back()] - v[ss.front()]) / double(ss.back()-ss.front()), emin = 1e300, emax = -1e300;
    for (int s : ss) {
      double e = v[s] - a * s;
      emin = std::min(emin, e);
      emax = std::max(emax, e);
    }
    size_t nh = limit ? std::min(limit, hands.size()) : hands.size();
    std::vector<Work> w(threads);
    std::vector<std::thread> ts;
    for (int k = 0; k < threads; k++)
      ts.emplace_back([&, k]() {
        w[k] = chunk(v, a, emin, emax, nh * k / threads, nh * (k + 1) / threads,
                     update);
      });
    for (auto &t : ts)
      t.join();
    Work out;
    for (const auto &x : w) {
      for (int s : ss)
        out.sum[s] += x.sum[s];
      out.convolutions += x.convolutions;
      out.changes += x.changes;
      out.min_gap = std::min(out.min_gap, x.min_gap);
    }
    double denominator = TOTAL;
    if (limit) {
      denominator = 0;
      for (size_t i = 0; i < nh; i++)
        denominator += hands[i].weight;
    }
    for (int s : ss)
      out.sum[s] /= denominator;
    return out;
  }
};
std::vector<long double> linear_solve(std::vector<std::vector<long double>> a,
                                      std::vector<long double> b) {
  int n = b.size();
  for (int c = 0; c < n; c++) {
    int pivot = c;
    for (int r = c + 1; r < n; r++)
      if (std::abs(a[r][c]) > std::abs(a[pivot][c]))
        pivot = r;
    if (std::abs(a[pivot][c]) < 1e-24L)
      throw std::runtime_error("singular policy matrix");
    std::swap(a[pivot], a[c]);
    std::swap(b[pivot], b[c]);
    long double div = a[c][c];
    for (int j = c; j < n; j++)
      a[c][j] /= div;
    b[c] /= div;
    for (int r = 0; r < n; r++)
      if (r != c) {
        long double f = a[r][c];
        for (int j = c; j < n; j++)
          a[r][j] -= f * a[c][j];
        b[r] -= f * b[c];
      }
  }
  return b;
}
void certify_policy(const fs::path &out, const Solver &sol,
                    const std::array<double, 121> &v) {
  const int n = sol.ss.size();
  struct Acc {
    std::vector<long double> p, r;
    Acc(int n) : p(n * n), r(n) {}
  };
  std::vector<Acc> acc;
  for (int k = 0; k < sol.threads; k++)
    acc.emplace_back(n);
  std::vector<std::thread> ts;
  for (int k = 0; k < sol.threads; k++)
    ts.emplace_back([&, k]() {
      auto &dst = acc[k];
      for (size_t hi = sol.hands.size() * k / sol.threads;
           hi < sol.hands.size() * (k + 1) / sol.threads; hi++) {
        const auto &h = sol.hands[hi];
        bool need[32] = {};
        for (int si = 0; si < n; si++)
          need[sol.policy[hi * n + si]] = true;
        double q[32][121];
        for (int m = 0; m < 32; m++)
          if (need[m])
            distribution(h.row[m], m, q[m]);
        for (int si = 0; si < n; si++) {
          int m = sol.policy[hi * n + si];
          dst.r[si] += static_cast<long double>(h.weight) * sol.ss[si] * 5 *
                       h.row[m].pay / DEN[m];
          for (int sj = 0; sj < n; sj++)
            dst.p[si * n + sj] +=
                static_cast<long double>(h.weight) * q[m][sol.ss[sj]];
        }
      }
    });
  for (auto &t : ts)
    t.join();
  Acc all(n);
  for (const auto &part : acc) {
    for (int i = 0; i < n * n; i++)
      all.p[i] += part.p[i];
    for (int i = 0; i < n; i++)
      all.r[i] += part.r[i];
  }
  for (auto &x : all.p)
    x /= TOTAL;
  for (auto &x : all.r)
    x /= TOTAL;
  long double row_error = 0;
  for (int si = 0; si < n; si++) {
    long double sum = 0;
    for (int sj = 0; sj < n; sj++)
      sum += all.p[si * n + sj];
    row_error = std::max(row_error, std::abs(sum - 1));
  }
  std::vector<std::vector<long double>> a(n, std::vector<long double>(n));
  std::vector<long double> b(n);
  for (int i = 0; i < n - 1; i++)
    for (int j = 0; j < n; j++)
      a[i][j] = (i == j ? 1.0L : 0.0L) - all.p[j * n + i];
  for (int j = 0; j < n; j++)
    a[n - 1][j] = 1;
  b[n - 1] = 1;
  auto pi = linear_solve(a, b);
  long double gain = 0, minpi = 1, norm = 0, staterr = 0;
  for (int i = 0; i < n; i++) {
    gain += pi[i] * all.r[i];
    norm += pi[i];
    minpi = std::min(minpi, pi[i]);
  }
  for (int j = 0; j < n; j++) {
    long double p = 0;
    for (int i = 0; i < n; i++)
      p += pi[i] * all.p[i * n + j];
    staterr = std::max(staterr, std::abs(p - pi[j]));
  }
  std::vector<std::vector<long double>> ap(n - 1,
                                           std::vector<long double>(n - 1));
  std::vector<long double> bp(n - 1);
  for (int i = 1; i < n; i++) {
    bp[i - 1] = all.r[i] - gain;
    for (int j = 1; j < n; j++)
      ap[i - 1][j - 1] = (i == j ? 1.0L : 0.0L) - all.p[i * n + j];
  }
  auto pv = linear_solve(ap, bp);
  pv.insert(pv.begin(), 0);
  long double err = 0, low = 1e300L, high = -1e300L;
  for (int i = 0; i < n; i++) {
    err = std::max(err, std::abs(pv[i] - v[sol.ss[i]]));
    long double delta = all.r[i] - pv[i];
    for (int j = 0; j < n; j++)
      delta += all.p[i * n + j] * pv[j];
    low = std::min(low, delta);
    high = std::max(high, delta);
  }
  std::ofstream o(out / "policy-certificate.json");
  o << std::setprecision(20) << "{\n\"gain\":" << gain
    << ",\"return\":" << gain / (10*NHANDS)
    << ",\"stationary_norm_error\":" << std::abs(norm - 1)
    << ",\"stationary_min_probability\":" << minpi
    << ",\"stationary_residual\":" << staterr
    << ",\"transition_row_error\":" << row_error
    << ",\"poisson_span\":" << high - low
    << ",\"bias_comparison_max_error\":" << err
    << ",\"arithmetic\":\"long double accumulation; Gaussian elimination "
       "policy evaluation\"\n}\n";
  std::cout << std::setprecision(15)
            << "independent policy return=" << gain / (10*NHANDS)
            << " transition_row_error=" << row_error
            << " stationary_residual=" << staterr
            << " poisson_span=" << high - low << " bias_error=" << err << "\n"
            << std::flush;
}

void dump_bias(const fs::path &p, const std::vector<int> &ss,
               const std::array<double, 121> &v, int it, double gain,
               double span, uint64_t changes, double /*seconds*/, double low,
               double high) {
  std::ofstream o(p);
  o << std::setprecision(17) << "{\n\"num_hands\":" << NHANDS << ",\"states\":[";
  for (size_t i = 0; i < ss.size(); i++)
    o << (i ? "," : "") << ss[i];
  o << "],\n\"values\":[";
  for (size_t i = 0; i < ss.size(); i++)
    o << (i ? "," : "") << v[ss[i]];
  o << "],\n\"gain\":" << gain << ",\"bellman_span\":" << span
    << ",\"iterations\":" << it
    << ",\"normalization_state\":" << NHANDS << ",\"policy_changes\":" << changes
    << ",\"gain_lower\":" << low << ",\"gain_upper\":" << high
    << ",\"tie_tolerance\":1e-9\n}\n";
}
int main(int argc, char **argv) {
  try {
    init();
    fs::path out = "validation/cabinet/generated", config;
    bool subsets_only = false;
    int threads = std::max(1u, std::thread::hardware_concurrency() / 2),
        maxit = 100;
    double tolerance = 1e-9;
    size_t pilot = 0;
    for (int i = 1; i < argc; i++) {
      std::string a = argv[i];
      if (a == "--output")
        out = argv[++i];
      else if (a == "--config")
        config = argv[++i];
      else if (a == "--subsets-only")
        subsets_only = true;
      else if (a == "--threads")
        threads = std::stoi(argv[++i]);
      else if (a == "--max-iterations")
        maxit = std::stoi(argv[++i]);
      else if (a == "--tolerance")
        tolerance = std::stod(argv[++i]);
      else if (a == "--pilot")
        pilot = std::stoul(argv[++i]);
      else
        throw std::runtime_error("unknown argument " + a);
    }
    if (threads < 1 || threads > 64 || maxit < 1 || !(tolerance > 0))
      throw std::runtime_error("invalid arguments");
    std::ifstream cfg(config);
    int declared_nc=0,declared_nd=0;
    if(!(cfg>>NHANDS>>declared_nc>>declared_nd) || declared_nc!=NC || declared_nd!=ND ||
        (NHANDS!=3 && NHANDS!=5 && NHANDS!=10))throw std::runtime_error("bad game config");
    for(int &p:PAY)if(!(cfg>>p) || p<0 || p>800)throw std::runtime_error("bad payout config");
    for(int &m:MUL)if(!(cfg>>m) || m<1 || m>12)throw std::runtime_error("bad multiplier config");
    for(int m:MUL)if(std::find(ALLOWED.begin(),ALLOWED.end(),m)==ALLOWED.end())ALLOWED.push_back(m);
    std::sort(ALLOWED.begin(),ALLOWED.end());
    fs::create_directories(out);
    auto subset = out / "subset_counts.dat";
    Table t =
        fs::exists(subset) ? read_subset(subset) : generate_subset(subset);
    if (subsets_only)
      return 0;
    auto cache = out / "canonical_counts.dat";
    std::vector<Hand> hs =
        fs::exists(cache) ? read_hands(cache) : generate_hands(cache, t);
    t = Table{};
    Solver sol(hs, threads);
    std::array<double, 121> v{};
    for (int s : sol.ss)
      v[s] = 4.95 * (s - NHANDS);
    auto tm = now();
    std::ofstream log(
        out / (pilot ? "pilot-progress.jsonl" : "solver-progress.jsonl"));
    for (int i = 1; i <= maxit; i++) {
      auto ti = now();
      auto w = sol.apply(v, true, pilot);
      double low = 1e300, high = -1e300;
      for (int s : sol.ss) {
        double d = w.sum[s] - v[s];
        low = std::min(low, d);
        high = std::max(high, d);
      }
      double span = high - low, g = w.sum[NHANDS];
      std::cout << std::setprecision(12) << "iteration=" << i << " gain=" << g
                << " span=" << span << " changes=" << w.changes
                << " convolutions=" << w.convolutions
                << " seconds=" << elapsed(ti) << "\n"
                << std::flush;
      log << std::setprecision(17) << "{\"iteration\":" << i
          << ",\"gain\":" << g << ",\"span\":" << span
          << ",\"changes\":" << w.changes
          << ",\"convolutions\":" << w.convolutions
          << ",\"seconds\":" << elapsed(ti) << "}\n"
          << std::flush;
      if (!pilot)
        dump_bias(out / "bias-progress.json", sol.ss, v, i, g, span, w.changes,
                  elapsed(tm), low, high);
      if (span < tolerance && w.changes == 0) {
        if (pilot) {
          std::cout << "PILOT ONLY; not a valid full-game strategy\n";
          return 0;
        }
        dump_bias(out / "bias.json", sol.ss, v, i, g, span, w.changes,
                  elapsed(tm), low, high);
        certify_policy(out, sol, v);
        std::cout << "converged return=" << std::setprecision(15) << g / (10*NHANDS)
                  << " seconds=" << elapsed(tm) << "\n";
        return 0;
      }
      for (int s : sol.ss)
        v[s] = w.sum[s] - g;
    }
    if (pilot) {
      std::cout << "PILOT ONLY; not a valid full-game strategy\n";
      return 0;
    }
    throw std::runtime_error(
        "not converged; progress saved, no final bias emitted");
  } catch (const std::exception &e) {
    std::cerr << "strategy generator: " << e.what() << "\n";
    return 1;
  }
}
