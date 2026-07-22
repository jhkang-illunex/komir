# -*- coding: utf-8 -*-
"""진단모델 베이스라인 학습 (월간 패널, 시간순 홀드아웃)"""
import duckdb, numpy as np, pandas as pd, json
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.inspection import permutation_importance

DB="/tmp/mdb.duckdb"
FEATS=["volatility_12w","import_hhi","import_yoy","import_cagr3","production_hhi",
       "spread_pct","geopolitical_risk","geo_macro","ref_price"]
con=duckdb.connect(DB, read_only=True)
# 월간 패널: 피처 월평균 + 타깃 월말(last)
df=con.execute(f"""
WITH w AS (
  SELECT commodity_code, date_trunc('month',obs_date) AS month, obs_date,
         {','.join(FEATS)}, teacher_supply_demand AS y
  FROM mart_weekly_diagnosis
  WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL
)
SELECT commodity_code, month,
       {','.join(f'avg({c}) AS {c}' for c in FEATS)},
       last(y ORDER BY obs_date) AS y
FROM w GROUP BY 1,2 ORDER BY commodity_code, month
""").df()
con.close()
print("월간 패널:", df.shape)

# 시간순 분할: 2025-01 이전 학습 / 이후 검증
df["month"]=pd.to_datetime(df["month"])
train=df[df.month< "2025-01-01"].copy()
test =df[df.month>="2025-01-01"].copy()
print(f"train {len(train)} / test {len(test)}  (test: 2025-01~)")

X_cols=FEATS+["commodity_code"]
Xtr,ytr=train[X_cols],train["y"].values
Xte,yte=test[X_cols],test["y"].values

# 0) 나이브: 광종별 학습기간 평균
naive_map=train.groupby("commodity_code")["y"].mean()
naive_pred=test["commodity_code"].map(naive_map).values
def rep(n,yt,yp): 
    return dict(model=n, MAE=round(mean_absolute_error(yt,yp),2), RMSE=round(float(np.sqrt(((yt-yp)**2).mean())),2), R2=round(r2_score(yt,yp),3))
results=[rep("Naive(광종평균)",yte,naive_pred)]

num=FEATS; cat=["commodity_code"]
# 1) Ridge + 광종더미 + 표준화 + 결측대치
pre=ColumnTransformer([
    ("num", Pipeline([("imp",SimpleImputer(strategy="median")),("sc",StandardScaler())]), num),
    ("cat", OneHotEncoder(handle_unknown="ignore"), cat)])
ridge=Pipeline([("pre",pre),("m",Ridge(alpha=1.0))]).fit(Xtr,ytr)
results.append(rep("Ridge(+광종더미)",yte,ridge.predict(Xte)))

# 2) HistGBM (결측 native 처리, 광종 ordinal)
Xtr2=Xtr.copy(); Xte2=Xte.copy()
codes={c:i for i,c in enumerate(sorted(df.commodity_code.unique()))}
Xtr2["commodity_code"]=Xtr2["commodity_code"].map(codes); Xte2["commodity_code"]=Xte2["commodity_code"].map(codes)
gbm=HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3,
      categorical_features=[len(FEATS)], random_state=42).fit(Xtr2,ytr)
results.append(rep("HistGBM(+광종)",yte,gbm.predict(Xte2)))

print("\n=== 회귀 성능 (test=2025~) ===")
for r in results: print("  ",r)

# 이진 위기분류 (타깃<20 = 위기)
thr=20
ytr_b=(ytr<thr).astype(int); yte_b=(yte<thr).astype(int)
auc=None
if yte_b.sum()>0 and yte_b.sum()<len(yte_b):
    clf=HistGradientBoostingClassifier(max_iter=300,learning_rate=0.05,max_depth=3,
        categorical_features=[len(FEATS)],random_state=42).fit(Xtr2,ytr_b)
    auc=round(roc_auc_score(yte_b, clf.predict_proba(Xte2)[:,1]),3)
print(f"\n=== 위기 이진분류(타깃<{thr}) AUC(test): {auc} | test 위기비율 {yte_b.mean():.2f} ===")

# 피처 중요도 (permutation, GBM)
pi=permutation_importance(gbm,Xte2,yte,n_repeats=10,random_state=42)
imp=sorted(zip(X_cols,pi.importances_mean),key=lambda x:-x[1])
print("\n=== 피처 중요도 (permutation, GBM) ===")
for f,v in imp: print(f"  {f:18s}: {v:.2f}")

# 저장
out="/sessions/dreamy-modest-lamport/mnt/광해광업/claude_output/model"
pd.DataFrame(results).to_csv(f"{out}/model_metrics.csv",index=False)
pd.DataFrame(imp,columns=["feature","perm_importance"]).to_csv(f"{out}/feature_importance.csv",index=False)
df.to_csv(f"{out}/monthly_panel.csv",index=False)
json.dump({"results":results,"auc_crisis":auc,"n_train":len(train),"n_test":len(test),
           "importance":[[f,round(float(v),3)] for f,v in imp]},
          open(f"{out}/model_summary.json","w"),ensure_ascii=False,indent=2)
print("\n저장: claude_output/model/ (metrics·importance·panel·summary)")
