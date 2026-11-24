export const criteriaVersion=2;
export function mealLabel(value:string){return ({breakfast:'早饭',lunch:'午饭',dinner:'晚饭',any:'未限定餐次'} as Record<string,string>)[value]||'未限定餐次';}
export function spiceLabel(min=0,max=2,specified=true){if(!specified)return '未限定口味';if(min===0&&max===0)return '不辣';if(min===1&&max===1)return '只要微辣';if(min>=1)return '喜欢辣（仅选有辣）';if(max===1)return '可接受微辣';return '能吃辣（也接受不辣）';}
export function calorieLabel(p:any,keys:string[]){
 const low=keys.includes('kcal_min'), high=keys.includes('kcal_max');
 const lower=(p.kcal_min_exclusive?'>':'≥')+p.kcal_min, upper=(p.kcal_max_exclusive?'<':'≤')+p.kcal_max;
 if(low&&high)return p.kcal_min_exclusive||p.kcal_max_exclusive?`${lower} 且 ${upper} kcal`:`${p.kcal_min}～${p.kcal_max} kcal`;
 if(high)return `${upper} kcal（未设下限）`;
 return low?`${lower} kcal（未设上限）`:'未设置热量限制';
}
export function savedCriteria(c:any){const keys=Object.keys(c);return [mealLabel(c.meal_period),keys.includes('budget')?`预算≤${c.budget}元`:'未设预算上限',calorieLabel(c,keys),spiceLabel(c.min_spice||0,c.max_spice??2,keys.includes('min_spice')||keys.includes('max_spice'))].join(' · ');}
export function resultCriteria(result:any){const p=result.params,keys=result.specified_conditions||result.memory_test?.specified_conditions||[];const loaded=result.memory_test?.memory_loaded;return [{label:'餐次',value:mealLabel(p.meal_period)},{label:'预算上限',value:keys.includes('budget')?`≤${p.budget}元`:loaded?'未设置':`${p.budget}元（演示默认）`},{label:'热量要求',value:loaded?calorieLabel(p,keys):`${p.kcal_min}～${p.kcal_max} kcal（演示默认）`},{label:'口味要求',value:spiceLabel(p.min_spice||0,p.max_spice,loaded?(keys.includes('min_spice')||keys.includes('max_spice')):true)+(!loaded?'（演示默认）':'')}];}
