import psycopg2

conn = psycopg2.connect(dbname='quantmind_v2', user='xin', password='quantmind', host='localhost')
cur = conn.cursor()

cur.execute('SELECT COUNT(*), COUNT(DISTINCT ts_code) FROM minute_bars')
r = cur.fetchone()
print(f'分钟K线: {r[0]:,}行, {r[1]}/5194只 ({r[1]/5194*100:.1f}%)')

cur.execute("SELECT factor_name, COUNT(*) FROM factor_values WHERE factor_name LIKE 'nb_%' GROUP BY factor_name ORDER BY factor_name")
nb = cur.fetchall()
print(f'\n北向RANKING因子: {len(nb)}个')
for name, cnt in nb:
    print(f'  {name:30s}: {cnt:>10,}行')

cur.execute('SELECT COUNT(*) FROM modifier_signals')
print(f'\nmodifier_signals: {cur.fetchone()[0]}行')

cur.execute("SELECT factor_name, recommended_template, ic_20d, ic_20d_tstat FROM factor_profile WHERE factor_name LIKE 'nb_%' ORDER BY factor_name")
profiles = cur.fetchall()
print(f'\n北向因子画像: {len(profiles)}条')
for name, tmpl, ic, t in profiles:
    print(f'  {name:30s}: tmpl={tmpl}, IC={ic}, t={t}')

cur.execute("SELECT COUNT(*) FROM symbols WHERE market='astock' AND industry_sw_l1 IS NOT NULL")
m = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM symbols WHERE market='astock'")
t = cur.fetchone()[0]
print(f'\n行业L1映射: {m}/{t} ({m/t*100:.1f}%)')

cur.execute("SELECT factor_name, COUNT(*) FILTER (WHERE neutral_value IS NOT NULL) as n FROM factor_values WHERE factor_name IN ('nb_increase_ratio_20d','nb_new_entry','nb_contrarian') GROUP BY factor_name")
print('\n北向因子中性化:')
for name, cnt in cur.fetchall():
    print(f'  {name}: {cnt:,}条')

conn.close()
