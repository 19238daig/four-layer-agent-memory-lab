-- meal-energy-v1 / 模拟数据演示估算。所有量转换为每份、可食、营养数据同口径克数。
WITH
nv AS (
 SELECT *,ROW_NUMBER() OVER(PARTITION BY mat_cd ORDER BY valid_from DESC,nut_id DESC) rn
 FROM nutrient_ver WHERE valid_from<=:as_of AND (valid_to IS NULL OR valid_to>:as_of)
),
rv AS (
 SELECT *,ROW_NUMBER() OVER(PARTITION BY item_cd ORDER BY valid_from DESC,ver_no DESC) rn
 FROM recipe_ver WHERE valid_from<=:as_of AND (valid_to IS NULL OR valid_to>:as_of)
),
pv AS (
 SELECT *,ROW_NUMBER() OVER(PARTITION BY sku_cd ORDER BY valid_from DESC,price_id DESC) rn
 FROM price_hist WHERE valid_from<=:as_of AND (valid_to IS NULL OR valid_to>:as_of)
),
line_basis AS (
 SELECT l.line_id,r.recipe_id,r.item_cd,l.mat_cd,m.nm material_name,l.qty,l.uom,l.wt_basis,
        n.nut_id,n.basis_cd,n.p_100,n.f_100,n.c_100,r.servings,
        l.qty*COALESCE(um.g_per_unit,ug.g_per_unit)*CASE WHEN l.gross_f=1 THEN m.edible_ratio ELSE 1 END
        *CASE WHEN l.wt_basis=n.basis_cd THEN 1
              WHEN l.wt_basis='raw' AND n.basis_cd='cooked' THEN cr.yield_factor
              WHEN l.wt_basis='cooked' AND n.basis_cd='raw' THEN 1.0/cr.yield_factor ELSE NULL END AS edible_g,
        CASE WHEN n.nut_id IS NULL OR n.p_100 IS NULL OR n.f_100 IS NULL OR n.c_100 IS NULL
          OR COALESCE(um.g_per_unit,ug.g_per_unit) IS NULL OR cr.rule_cd IS NULL
          OR l.wt_basis NOT IN ('raw','cooked') OR l.qty<=0 OR n.p_100<0 OR n.f_100<0 OR n.c_100<0 THEN 1 ELSE 0 END AS missing
 FROM rv r JOIN recipe_line l ON l.recipe_id=r.recipe_id
 JOIN material_dict m ON m.mat_cd=l.mat_cd
 LEFT JOIN nv n ON n.mat_cd=l.mat_cd AND n.rn=1
 LEFT JOIN unit_map um ON um.mat_cd=l.mat_cd AND um.uom=l.uom
 LEFT JOIN unit_map ug ON ug.mat_cd='*' AND ug.uom=l.uom
 LEFT JOIN cook_rule cr ON cr.rule_cd=r.rule_cd WHERE r.rn=1
),
line_energy AS (
 SELECT *,edible_g/100.0*(4*p_100+9*f_100+4*c_100)/servings AS kcal_per_portion
 FROM line_basis
),
recipe_energy AS (
 SELECT r.recipe_id,r.item_cd,r.oil_g,r.servings,cr.oil_lo,cr.oil_hi,
        COUNT(l.line_id) line_count,
        COALESCE(SUM(l.missing),0)+CASE WHEN COUNT(l.line_id)=0 OR r.oil_g IS NULL OR r.oil_g<0 OR cr.rule_cd IS NULL THEN 1 ELSE 0 END missing_count,
        SUM(l.kcal_per_portion) base_kcal,
        9*r.oil_g/r.servings*cr.oil_lo oil_kcal_lo,
        9*r.oil_g/r.servings*cr.oil_hi oil_kcal_hi
 FROM rv r LEFT JOIN line_energy l ON l.recipe_id=r.recipe_id
 LEFT JOIN cook_rule cr ON cr.rule_cd=r.rule_cd WHERE r.rn=1 GROUP BY r.recipe_id
),
sku_energy AS (
 SELECT s.sku_cd,s.item_cd,s.spec_nm,s.mult,i.nm,i.shop_cd,i.hot_lv,
        r.recipe_id,p.price_id,p.amt,
        CASE WHEN r.recipe_id IS NULL THEN 1 ELSE r.missing_count END missing_count,
        s.mult*r.base_kcal base_kcal,s.mult*r.oil_kcal_lo oil_kcal_lo,s.mult*r.oil_kcal_hi oil_kcal_hi
 FROM sku_spec s JOIN menu_item i ON i.item_cd=s.item_cd
 JOIN shop_mst sh ON sh.shop_cd=i.shop_cd
 LEFT JOIN recipe_energy r ON r.item_cd=s.item_cd
 LEFT JOIN pv p ON p.sku_cd=s.sku_cd AND p.rn=1
 WHERE s.active_f=1 AND i.active_f=1 AND sh.active_f=1
),
offering_parts AS (
 SELECT 'SKU:'||s.sku_cd offer_id,s.nm||' · '||s.spec_nm offer_name,s.shop_cd,
        s.amt price,s.hot_lv,s.sku_cd,s.recipe_id,s.price_id,1.0 part_qty,
        s.missing_count,s.base_kcal,s.oil_kcal_lo,s.oil_kcal_hi FROM sku_energy s
 UNION ALL
 SELECT 'COMBO:'||c.combo_cd,c.nm,c.shop_cd,c.amt,s.hot_lv,s.sku_cd,s.recipe_id,s.price_id,cl.qty,
        CASE WHEN s.sku_cd IS NULL THEN 1 ELSE s.missing_count END,
        cl.qty*s.base_kcal,cl.qty*s.oil_kcal_lo,cl.qty*s.oil_kcal_hi
 FROM combo_hdr c JOIN shop_mst sh ON sh.shop_cd=c.shop_cd
 LEFT JOIN combo_line cl ON cl.combo_cd=c.combo_cd
 LEFT JOIN sku_energy s ON s.sku_cd=cl.sku_cd
 WHERE c.active_f=1 AND sh.active_f=1
),
offers AS (
 SELECT offer_id,offer_name,shop_cd,price,MAX(hot_lv) hot_lv,SUM(missing_count) missing_count,
        SUM(CASE WHEN hot_lv IS NULL OR hot_lv NOT IN (0,1,2) THEN 1 ELSE 0 END) spice_missing,
        SUM(base_kcal) base_kcal,SUM(oil_kcal_lo) oil_kcal_lo,SUM(oil_kcal_hi) oil_kcal_hi,
        SUM(base_kcal)+SUM(oil_kcal_lo) raw_lo,SUM(base_kcal)+SUM(oil_kcal_hi) raw_hi,
        GROUP_CONCAT(sku_cd) sku_ids,GROUP_CONCAT(recipe_id) recipe_ids,GROUP_CONCAT(price_id) price_ids
 FROM offering_parts GROUP BY offer_id
),
evaluated AS (
 SELECT offer_id,offer_name,shop_cd,price,CASE WHEN spice_missing>0 THEN NULL ELSE hot_lv END hot_lv,missing_count,
        CASE WHEN missing_count=0 THEN ROUND(raw_lo,1) END kcal_lo,
        CASE WHEN missing_count=0 THEN ROUND(raw_hi,1) END kcal_hi,
        ROUND(base_kcal,2) base_kcal,ROUND(oil_kcal_lo,2) oil_kcal_lo,ROUND(oil_kcal_hi,2) oil_kcal_hi,
        sku_ids,recipe_ids,price_ids,
        CASE WHEN missing_count>0 OR price IS NULL OR price<0 OR spice_missing>0 THEN 'unknown'
             WHEN price>:budget OR hot_lv<:min_spice OR hot_lv>:max_spice OR raw_hi<:kcal_min OR raw_lo>:kcal_max
                  OR (:kcal_min_exclusive=1 AND raw_hi=:kcal_min) OR (:kcal_max_exclusive=1 AND raw_lo=:kcal_max) THEN 'fail'
             WHEN (raw_lo>:kcal_min OR (:kcal_min_exclusive=0 AND raw_lo=:kcal_min))
                  AND (raw_hi<:kcal_max OR (:kcal_max_exclusive=0 AND raw_hi=:kcal_max)) THEN 'pass' ELSE 'uncertain' END status,
        CASE WHEN missing_count>0 THEN '关键营养、单位、用油或配方数据缺失'
             WHEN price IS NULL OR price<0 OR spice_missing>0 THEN '价格或辣度缺失/异常'
             WHEN price>:budget THEN '超过预算' WHEN hot_lv<:min_spice OR hot_lv>:max_spice THEN '辣度不符'
             WHEN raw_hi<:kcal_min OR (:kcal_min_exclusive=1 AND raw_hi=:kcal_min) THEN '未达到热量下限'
             WHEN raw_lo>:kcal_max OR (:kcal_max_exclusive=1 AND raw_lo=:kcal_max) THEN '超出热量上限'
             WHEN (raw_lo>:kcal_min OR (:kcal_min_exclusive=0 AND raw_lo=:kcal_min))
                  AND (raw_hi<:kcal_max OR (:kcal_max_exclusive=0 AND raw_hi=:kcal_max)) THEN '热量区间、预算、辣度均符合'
             ELSE '热量区间仅部分重叠' END reason
 FROM offers WHERE (:offer_id='' OR offer_id=:offer_id)
 AND (:name='' OR offer_id IN (
    SELECT op.offer_id FROM offering_parts op JOIN sku_spec ss ON ss.sku_cd=op.sku_cd
    JOIN menu_item mi ON mi.item_cd=ss.item_cd
    WHERE INSTR(mi.nm,:name)>0 OR INSTR(op.offer_name,:name)>0
       OR EXISTS(SELECT 1 FROM item_alias ia WHERE ia.item_cd=mi.item_cd AND INSTR(ia.alias_txt,:name)>0)
 ))
)
-- MODEL_SELECT: 下方最终 SELECT 由模型生成；上方为已核验公式模板。
SELECT * FROM evaluated
ORDER BY CASE status WHEN 'pass' THEN 0 WHEN 'uncertain' THEN 1 WHEN 'fail' THEN 2 ELSE 3 END, price, offer_id
LIMIT :limit;
