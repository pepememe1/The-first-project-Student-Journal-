# %% [markdown]
# # Расписание для обсерватории — решение
# Подход:
# 1. Сегментация шагов на «ночи» по высоте Солнца (вечер → полночь → утро).
# 2. Модель вероятности успеха наблюдения (LightGBM, монотонно убывает по температуре), признаки — только те, что известны в тесте
#    (температура, свойства объекта, Солнце/Луна, позиция в ночи, было ли наблюдение на прошлых шагах).
# 3. Линейная модель динамики температуры телескопа (отдельно внутри ночи и через день) с лаговым эффектом нагрева.
# 4. Монте-Карло симулятор открытого плана (принудительный отдых после отказа, лимит 45 отдыхов, случайный эффект сеанса).
# 5. Оптимизация плана имитацией отжига по критерию E[баллы · 1(отдыхов ≤ 45)].

# %%
import numpy as np, pandas as pd, lightgbm as lgb, time, os
from collections import Counter
from sklearn.model_selection import GroupKFold
from sklearn.metrics import log_loss, roc_auc_score
DATA = os.environ.get('DATA_DIR', 'data')   # папка с train.csv, context.csv, slots.csv, objects.csv
TYPES = ['A1','A2','A3','B1','B2','B3','B4','C1','C2','C3']
ACTS = TYPES + ['REST','REST_FORCED']
HEAVY = {'A1','A2','A3','B1','B2'}; LIGHT = {'B3','B4','C1','C2','C3'}
VALUE = {'A':20,'B':5,'C':1}
train = pd.read_csv(f'{DATA}/train.csv'); ctx = pd.read_csv(f'{DATA}/context.csv')
slots = pd.read_csv(f'{DATA}/slots.csv')
objs = pd.read_csv(f'{DATA}/objects.csv' if os.path.exists(f'{DATA}/objects.csv') else f'{DATA}/objects_1.csv')
print(train.shape, ctx.shape, slots.shape, objs.shape)

# %% [markdown]
# ## 1. Ночи
# Каждая ночь начинается вечером при почти постоянной (медленно дрейфующей) высоте Солнца. Ищем самую длинную «цепочку»
# локальных максимумов (или шагов сразу после них) с близкими значениями высоты Солнца — это начала ночей.

# %%
def _track(cands, s, seed, tol):
    acc = [seed]; ref = s[seed]
    for c in [c for c in cands if c > seed]:
        if abs(s[c]-ref) <= tol: acc.append(c); ref = s[c]
    ref = s[seed]
    for c in [c for c in cands if c < seed][::-1]:
        if abs(s[c]-ref) <= tol: acc.append(c); ref = s[c]
    return sorted(acc)

def night_starts(sun, tol=0.45):
    s = np.asarray(sun, float); n = len(s)
    ext = np.r_[-np.inf, s, -np.inf]
    lmax = [i for i in range(n) if ext[i+1] >= ext[i] and ext[i+1] > ext[i+2]]
    cands = set(lmax)
    for i in lmax:
        if i+1 < n and (i+2 >= n or s[i+2] < s[i+1]) and s[i+1] < s[i]:
            cands.add(i+1)
    cands = sorted(cands); best = None
    for seed in cands:
        tr_ = _track(cands, s, seed, tol)
        key = (len(tr_), np.mean(s[tr_]))
        if best is None or key > best[0]: best = (key, tr_)
    flag = np.zeros(n, bool); flag[best[1]] = True
    return flag

def night_features(sun):
    st = night_starts(sun); n = len(st)
    nid = np.cumsum(st); pos = np.zeros(n, int); c = -1
    for i in range(n):
        c = 0 if st[i] else c+1; pos[i] = c
    rem = np.zeros(n, int); L = np.zeros(n, int)
    for v in np.unique(nid):
        idx = np.where(nid == v)[0]; rem[idx] = idx[-1]-idx; L[idx] = len(idx)
    return st.astype(int), nid, pos, rem, L

def add_night(df, key):
    parts = []
    for _, g in df.groupby(key, sort=False):
        st, nid, pos, rem, L = night_features(g.sun_altitude.values)
        parts.append(pd.DataFrame({'st':st,'nid':nid,'pos':pos,'rem':rem,'L':L}, index=g.index))
    return df.join(pd.concat(parts))

def grp(a):
    return 'H' if a in HEAVY else 'L' if a in LIGHT else 'R' if a == 'REST' else 'F'

def add_lags(df, key):
    g = df.groupby(key, sort=False)
    df['g'] = df.action.map(grp)
    obs = df.g.isin(['H','L']).astype(int)
    df['o1'] = obs.groupby(df[key]).shift(1).fillna(0).astype(int)
    df['o2'] = obs.groupby(df[key]).shift(2).fillna(0).astype(int)
    df['p1F'] = (df.g == 'F').astype(int).groupby(df[key]).shift(1).fillna(0).astype(int)
    df['f1'] = (1-df.result).groupby(df[key]).shift(1).fillna(0).astype(int)
    for c in ['temperature','sun_altitude','st']:
        df[c+'_n'] = g[c].shift(-1)
    return df

tr = add_lags(add_night(train, 'series_id'), 'series_id')
print('ночей в train:', tr.st.sum(), '| средний скачок температуры в начале ночи:',
      round(tr.groupby('series_id').temperature.diff()[tr.st == 1].mean(), 2))
print(tr.groupby('rem').apply(lambda d: d[~d.action.str.startswith('REST')].result.mean()).head(6).round(3).rename('успех по rem (0 = последний шаг ночи)'))

# %% [markdown]
# ## 2. Модель успеха наблюдения
# Погода (облака, температура воздуха) в тесте скрыта, поэтому модель использует только наблюдаемые признаки.
# Ключевые: температура телескопа (монотонно ↓), тип/блеск объекта, последний шаг ночи (rem=0 — почти всегда отказ для A),
# было ли наблюдение на шагах t-1, t-2 (скрытый нагрев).

# %%
SUCC_FEATS = ['temperature','typ','cls','object_magnitude','object_color','object_altitude','moon_separation',
              'sun_altitude','moon_altitude','moon_illumination','ambient_temperature','pos','last','sun_n2','o1','o2']
def succ_frame(df):
    df = df.copy()
    df['typ'] = df.action.map({a:i for i,a in enumerate(TYPES)})
    df['cls'] = df.typ.map(lambda i: 0 if i < 3 else (1 if i < 7 else 2))
    df['last'] = (df.rem == 0).astype(int)
    df['sun_n2'] = df.sun_altitude_n.fillna(df.sun_altitude)
    return df

LGB_PARAMS = dict(n_estimators=800, learning_rate=0.01, num_leaves=15, min_child_samples=40, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=1, deterministic=True, force_row_wise=True)
def fit_success(df, seeds=(0,1,2,3,4)):
    ob = succ_frame(df[~df.action.str.startswith('REST')])
    mono = [-1 if f == 'temperature' else 0 for f in SUCC_FEATS]
    return [lgb.LGBMClassifier(**LGB_PARAMS, monotone_constraints=mono, random_state=s).fit(ob[SUCC_FEATS], ob.result) for s in seeds]
def predict_success(ms, X):
    return np.mean([m.predict_proba(X[SUCC_FEATS])[:,1] for m in ms], axis=0)

ob_all = succ_frame(tr[~tr.action.str.startswith('REST')])
oof = np.zeros(len(ob_all))
for a, b in GroupKFold(5).split(ob_all, groups=ob_all.series_id):
    ms = fit_success(tr[tr.series_id.isin(ob_all.iloc[a].series_id.unique())], seeds=(0,))
    oof[b] = predict_success(ms, ob_all.iloc[b])
print(f'CV (по сеансам): logloss {log_loss(ob_all.result, oof):.4f}, AUC {roc_auc_score(ob_all.result, oof):.4f}')
for c in range(3):
    m_ = (ob_all.cls == c).values
    print(f'  класс {"ABC"[c]}: logloss {log_loss(ob_all.result[m_], oof[m_]):.4f}')
cal = pd.DataFrame({'p':oof,'y':ob_all.result.values,'cls':ob_all.cls.values})
cal['bin'] = pd.cut(cal.p, [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1])
print(cal[cal.cls == 0].groupby('bin', observed=True).agg(pred=('p','mean'), fact=('y','mean'), n=('y','size')).round(3).T)
succ_models = fit_success(tr)

# %% [markdown]
# ## 3. Модель температуры телескопа
# Внутри ночи: T(t+1) = a·T(t) + эффект действия t + лаговый нагрев от наблюдения на t-1 + ...; через день — отдельная регрессия.
# Остатки берём эмпирические (бутстреп) для симуляции.

# %%
def temp_design(d, ov):
    T = d.temperature.values; h = np.maximum(T-28, 0)
    gH = (d.g == 'H').values.astype(float); gL = (d.g == 'L').values.astype(float)
    X = {'T':T, 'amb':d.ambient_temperature.values, 'sun_n':d.sun_altitude_n.values, 'fail':(1-d.result).values,
         'o1':d.o1.values, 'p1F':d.p1F.values, 'f1':d.f1.values, 'o2':d.o2.values, 'hH':h*gH, 'hL':h*gL, 'h':h}
    if not ov:
        X['sun'] = d.sun_altitude.values; X['pos'] = d.pos.values
        for a in ACTS: X['a_'+a] = (d.action == a).values.astype(float)
    else:
        X['one'] = np.ones(len(d)); X['gH'] = gH; X['gL'] = gL; X['gF'] = (d.g == 'F').values.astype(float)
    return pd.DataFrame(X)

def fit_temp(df):
    t = df.dropna(subset=['temperature_n']); out = {}
    for ov in (False, True):
        d = t[t.st_n == int(ov)]; X = temp_design(d, ov)
        cv_r = np.zeros(len(d))
        for a, b in GroupKFold(5).split(d, groups=d.series_id):
            c, *_ = np.linalg.lstsq(X.values[a], d.temperature_n.values[a], rcond=None)
            cv_r[b] = d.temperature_n.values[b] - X.values[b] @ c
        c, *_ = np.linalg.lstsq(X.values, d.temperature_n.values, rcond=None)
        out[ov] = dict(coef=pd.Series(c, index=X.columns), resid=d.temperature_n.values - X.values @ c, cv_sd=cv_r.std())
    return out
tm = fit_temp(tr)
for ov in (False, True):
    print('через день' if ov else 'внутри ночи', '| CV остаток sd =', round(tm[ov]['cv_sd'], 3))
    print('  ', tm[ov]['coef'].round(3).to_dict())

# %% [markdown]
# ## 4. Тестовые сеансы: таблицы вероятностей и переходов
# Для каждого объекта заранее считаем P(успех | T, o1, o2) на сетке температур — симуляция затем делает только интерполяцию.

# %%
TGRID = np.arange(0.0, 60.01, 0.25); G0, DG = TGRID[0], TGRID[1]-TGRID[0]
def logit(p): p = np.clip(p, 1e-4, 1-1e-4); return np.log(p/(1-p))

def build_test(k):
    c = ctx[ctx.test_id == k].sort_values('step_id').reset_index(drop=True)
    s = slots[slots.test_id == k].sort_values('step_id')
    cols = ['step_id','sun_altitude','moon_altitude','moon_illumination','ambient_temperature']
    full = pd.concat([c[cols], s[cols]], ignore_index=True)
    st, nid, pos, rem, L = night_features(full.sun_altitude.values)
    full['st'] = st; full['pos'] = pos; full['rem'] = rem; full['L'] = L
    full['sun_altitude_n'] = full.sun_altitude.shift(-1)
    full = full.set_index('step_id'); amb = float(full.ambient_temperature.iloc[0])
    o = objs[objs.test_id == k].copy(); o['action'] = o.slot_id.str.split('_').str[0]
    for col in ['sun_altitude','moon_altitude','moon_illumination','ambient_temperature','pos','rem','L','sun_altitude_n']:
        o[col] = o.step_id.map(full[col])
    # проверка: все доступные объекты есть в objects.csv и на своих шагах
    avail = {(r.step_id, x) for r in s.itertuples() for x in r.available_object_ids.split('|')}
    assert avail == set(zip(o.step_id, o.slot_id)), 'objects/slots mismatch'
    step_objs = {st_: [] for st_ in range(11, 111)}; Ltab = {}
    for row in o.itertuples(index=False):
        X = pd.DataFrame([row._asdict()]*(4*len(TGRID)))
        X['temperature'] = np.tile(TGRID, 4)
        X['o1'] = np.repeat([0,0,1,1], len(TGRID)); X['o2'] = np.repeat([0,1,0,1], len(TGRID))
        p = predict_success(succ_models, succ_frame(X)).reshape(4, len(TGRID))
        p = np.minimum.accumulate(p, axis=1)          # монотонность по T
        Ltab[row.slot_id] = logit(p)
        step_objs[row.step_id].append((row.slot_id, row.action))
    trans = {}
    for st_ in range(10, 110):
        ov = bool(full.loc[st_+1, 'st']); cf = tm[ov]['coef']; f = full.loc[st_]
        if not ov:
            base = cf['amb']*amb + cf['sun_n']*full.loc[st_+1,'sun_altitude'] + cf['sun']*f.sun_altitude + cf['pos']*f.pos
            eff = {a: cf['a_'+a] for a in ACTS}
        else:
            base = cf['one'] + cf['amb']*amb + cf['sun_n']*full.loc[st_+1,'sun_altitude']
            eff = {a: {'H':cf['gH'],'L':cf['gL'],'F':cf['gF'],'R':0.0}[grp(a)] for a in ACTS}
        trans[st_] = dict(ov=ov, base=base, eff=eff, **{n: cf[n] for n in ['T','fail','o1','p1F','f1','o2','hH','hL','h']})
    # состояние перед шагом 11 из контекста
    g_ = c.action.map(grp).values; obs = np.isin(g_, ['H','L']).astype(int); fail = (1-c.result.values)
    forced0 = 0
    for i in range(len(c)):
        if obs[i] and fail[i]: forced0 = max(0, i+3-(len(c)-1))
    last = dict(T=float(c.temperature.iloc[-1]), act=c.action.iloc[-1], fail=int(fail[-1]),
                o1=int(obs[-2]), o2=int(obs[-3]), p1F=int(g_[-2] == 'F'), f1=int(fail[-2]))
    nxt = dict(o1=int(obs[-1]), o2=int(obs[-2]), p1F=int(g_[-1] == 'F'), f1=int(fail[-1]))
    return dict(k=k, full=full, step_objs=step_objs, Ltab=Ltab, trans=trans, last=last, nxt=nxt, forced0=forced0)

tests = {k: build_test(k) for k in (1, 2, 3)}
for k, tb in tests.items():
    ns = [s_ for s_ in range(11, 111) if tb['full'].loc[s_, 'st'] == 1]
    print(f'тест {k}: T10={tb["last"]["T"]:.2f}, действие шага 10 = {tb["last"]["act"]}, '
          f'принудительных отдыхов в начале: {tb["forced0"]}, ночей в 11–110: {len(ns)}')

# %% [markdown]
# ## 5. Симулятор плана (векторно по R прогонам)
# Состояние прогона: T, o1, o2 (наблюдение на t-1, t-2), p1F, f1, счётчик принудительного отдыха, число отдыхов, баллы.
# Случайный эффект сеанса: сдвиг логита успеха z ~ N(0, 0.3²) на прогон (оценён по сверхдисперсии успехов по сеансам в train).

# %%
class Sim:
    def __init__(self, tb, R=1000, seed=0, z_sd=0.3, max_rest=45):
        self.tb, self.R, self.max_rest = tb, R, max_rest
        rng = np.random.default_rng(seed)
        self.U = rng.random((100, R))
        self.z = rng.normal(0, z_sd, R)
        self.noise = np.zeros((101, R))
        for j, s_ in enumerate(range(10, 110)):
            pool = tm[tb['trans'][s_]['ov']]['resid']
            self.noise[j] = rng.choice(pool, R)
        self.steps = list(range(11, 111))
        self.choices = [[('', 'REST')] + tb['step_objs'][s_] for s_ in self.steps]
        L, n = tb['last'], tb['nxt']; tr_ = tb['trans'][10]
        T = self._trans(tr_, np.full(R, L['T']), np.full(R, tr_['eff'][L['act']]), np.full(R, grp(L['act'])),
                        np.full(R, L['fail'], bool), L['o1'], L['p1F'], L['f1'], L['o2']) + self.noise[0]
        z = lambda v: np.full(R, v, dtype=np.int64)
        self.init = (T, z(n['o1']), z(n['o2']), z(n['p1F']), z(n['f1']), z(tb['forced0']), z(0), np.zeros(R))
    @staticmethod
    def _trans(tr_, T, eff, g, failed, o1, p1F, f1, o2):
        h = np.maximum(T-28, 0)
        return (tr_['base'] + tr_['T']*T + eff + tr_['fail']*failed + tr_['o1']*o1 + tr_['p1F']*p1F + tr_['f1']*f1
                + tr_['o2']*o2 + (tr_['hH']*(g == 'H') + tr_['hL']*(g == 'L') + tr_['h'])*h)
    def step(self, j, choice, state):
        T, o1, o2, p1F, f1, forced, rests, score = state
        tb, R = self.tb, self.R; s_ = self.steps[j]; slot, act = choice
        isf = forced > 0
        if act == 'REST':
            rests = rests + 1; failed = np.zeros(R, bool); obs_now = np.zeros(R, np.int64)
        else:
            rests = rests + isf
            lt = tb['Ltab'][slot]; r_ = o1*2+o2
            u = np.clip((T-G0)/DG, 0, len(TGRID)-1.001); i = u.astype(np.int64); w = u-i
            lg = lt[r_, i]*(1-w) + lt[r_, i+1]*w + self.z
            succ = (self.U[j] < 1/(1+np.exp(-lg))) & ~isf
            failed = ~succ & ~isf; obs_now = (~isf).astype(np.int64)
            score = score + VALUE[act[0]]*succ
        if s_ < 110:
            tr_ = tb['trans'][s_]
            a_eff = np.where(isf, tr_['eff']['REST_FORCED'], tr_['eff'][act])
            g = np.where(isf, 'F', grp(act))
            T = self._trans(tr_, T, a_eff, g, failed, o1, p1F, f1, o2) + self.noise[j+1]
        forced = np.where(isf, forced-1, np.where(failed, 3, 0))
        return (T, obs_now, o1, isf.astype(np.int64), failed.astype(np.int64), forced, rests, score)
    def full(self, plan):
        st = [self.init]
        for j in range(100): st.append(self.step(j, plan[j], st[-1]))
        return st
    def obj(self, state, pen=5.0):
        # E[баллы·1(отдыхов ≤ max_rest)] минус мягкий штраф за превышение — даёт «градиент» из недопустимой области
        rests = state[6]
        return float(np.mean(state[7]*(rests <= self.max_rest)) - pen*np.mean(np.maximum(rests-self.max_rest, 0)))
    def evaluate(self, plan):
        fin = self.full(plan)[-1]; score, rests = fin[7], fin[6]; ok = rests <= self.max_rest
        return dict(value=float(np.mean(score*ok)), score=float(score.mean()), p_ok=float(ok.mean()),
                    rests=float(rests.mean()), rests_q95=float(np.quantile(rests, .95)))

# %% [markdown]
# ## 6. Оптимизация плана: имитация отжига
# Ход: на случайном шаге заменить действие на случайный доступный объект или REST; пересчёт симуляции с изменённого шага.
# Критерий: E[баллы · 1(отдыхов ≤ M)] − 5·E[превышение M] на общих случайных числах (R=1000).
# M ≤ 45 — «внутренний» лимит: запас на случай, если реальность хуже модели. Перебираем M ∈ {38, 40, 42},
# каждый план проверяем на независимых R=10000 прогонах с настоящим лимитом 45 и выбираем
# лучший по E[баллы·1(отдыхов ≤ 45)] среди планов с P(отдыхов ≤ 45) ≥ 0.95.

# %%
def init_plan(sim, lam=10.0, Tref=24.0):
    tb = sim.tb; plan = []
    for ch in sim.choices:
        def u(c):
            if c[1] == 'REST': return -lam*0.8
            p = 1/(1+np.exp(-np.interp(Tref, TGRID, tb['Ltab'][c[0]][0]))); return VALUE[c[1][0]]*p - lam*3*(1-p)
        plan.append(max(ch, key=u))
    return plan

def anneal(sim, plan, iters, T0=3.0, T1=0.03, seed=0, log_every=10000):
    rng = np.random.default_rng(seed); plan = list(plan)
    states = sim.full(plan); cur = sim.obj(states[-1]); best, best_plan = cur, list(plan)
    j_min = int(sim.tb['forced0']); t0 = time.time()
    for it in range(iters):
        temp = T0*(T1/T0)**(it/iters)
        j = int(rng.integers(j_min, 100)); ch = sim.choices[j]
        c = ch[int(rng.integers(len(ch)))]
        if c == plan[j]: continue
        old = plan[j]; plan[j] = c
        st, new = states[j], []
        for jj in range(j, 100):
            st = sim.step(jj, plan[jj], st); new.append(st)
        v = sim.obj(st)
        if v >= cur or rng.random() < np.exp((v-cur)/temp):
            cur = v; states[j+1:] = new
            if v > best: best, best_plan = v, list(plan)
        else:
            plan[j] = old
        if log_every and (it+1) % log_every == 0:
            print(f'    итерация {it+1}: текущее {cur:.2f}, лучшее {best:.2f} ({time.time()-t0:.0f} c)', flush=True)
    return best_plan, best

# %%
SA_ITERS = 40000
CONFIGS = [(k, M) for k in (1, 2, 3) for M in (38, 40, 42)]
def run_job(job):
    k, M = job
    sim = Sim(tests[k], R=1000, seed=k, max_rest=M)
    plan, best = anneal(sim, init_plan(sim), SA_ITERS, seed=10*k+M, log_every=0)
    val = Sim(tests[k], R=10000, seed=1000+k).evaluate(plan)
    pess = Sim(tests[k], R=10000, seed=2000+k, z_sd=0.5).evaluate(plan)
    return dict(test=k, M=M, opt=best, plan=plan, **val, pess_value=pess['value'], pess_p_ok=pess['p_ok'])

t0 = time.time()
try:
    import multiprocessing as mp
    with mp.get_context('fork').Pool(4) as pool:
        results = pool.map(run_job, CONFIGS)
except Exception as e:   # нет fork (Windows/macOS spawn) — считаем последовательно, результат тот же
    print('параллельный запуск недоступен, считаю последовательно:', e)
    results = [run_job(j) for j in CONFIGS]
print(f'оптимизация заняла {time.time()-t0:.0f} c')
res = pd.DataFrame([{k: v for k, v in r.items() if k != 'plan'} for r in results])
print(res.round(3).to_string(index=False))

# %%
def select(rs):
    good = [r for r in rs if r['p_ok'] >= 0.95]
    return max(good, key=lambda r: r['value']) if good else max(rs, key=lambda r: r['value'] - 500*(0.95-r['p_ok']))
plans, chosen = {}, []
for k in (1, 2, 3):
    r = select([r for r in results if r['test'] == k]); plans[k] = r['plan']
    chosen.append({k_: v for k_, v in r.items() if k_ != 'plan'})
    print(f'тест {k}: выбран M={r["M"]} | E[баллы·ok]={r["value"]:.1f}, E[баллы]={r["score"]:.1f}, '
          f'P(отдыхов≤45)={r["p_ok"]:.3f}, отдыхов в среднем {r["rests"]:.1f} | стресс-тест: {r["pess_value"]:.1f} (P={r["pess_p_ok"]:.3f})')
    print('   действия:', dict(Counter(a for _, a in r['plan'][tests[k]['forced0']:])))
print('Ожидаемая сумма по трём тестам:', round(sum(c['value'] for c in chosen), 1))

# %% [markdown]
# ## 7. Файл ответа
# На шагах, которые гарантированно станут принудительным отдыхом (отказ в конце контекста), действие игнорируется —
# ставим самый надёжный объект шага (а не REST).

# %%
rows = []
for k in (1, 2, 3):
    tb = tests[k]; plan = list(plans[k])
    for j in range(tb['forced0']):
        plan[j] = max(tb['step_objs'][11+j], key=lambda c: tb['Ltab'][c[0]][0][int((25-G0)/DG)])
    for j, (slot, act) in enumerate(plan):
        rows.append(dict(test_id=k, step=11+j, action=act, slot_id=slot if act != 'REST' else ''))
sub = pd.DataFrame(rows)
# проверки формата
assert len(sub) == 300 and sub.groupby('test_id').size().eq(100).all()
assert all(sorted(g.step) == list(range(11, 111)) for _, g in sub.groupby('test_id'))
avail = {(r.test_id, r.step_id): set(r.available_object_ids.split('|')) for r in slots.itertuples()}
for r in sub.itertuples():
    if r.action == 'REST': assert r.slot_id == ''
    else: assert r.slot_id in avail[(r.test_id, r.step)] and r.slot_id.split('_')[0] == r.action
assert not sub[sub.action != 'REST'].duplicated(['test_id', 'slot_id']).any()
print('строк REST в файле по тестам:', sub[sub.action == 'REST'].groupby('test_id').size().to_dict())
# контрольная симуляция итогового файла
for k in (1, 2, 3):
    p_ = [(r.slot_id, r.action) for r in sub[sub.test_id == k].itertuples()]
    print(f'тест {k}:', {a: round(b, 3) for a, b in Sim(tests[k], R=10000, seed=3000+k).evaluate(p_).items()})
sub.to_csv('submission.csv', index=False)
print(sub.head(12).to_string(index=False))
print('submission.csv сохранён:', sub.shape)
