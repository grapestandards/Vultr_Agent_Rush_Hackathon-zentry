import { fail } from '@sveltejs/kit';
import { api } from '#lib/server/api.ts';
import { FEATURE_GROUPS, type ModelVersion, type TrainRun } from '#lib/tuning.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, depends }) => {
	depends('app:tuning');
	const sb = locals.supabase;
	const [{ data: models }, { data: runs }, config] = await Promise.all([
		sb.from('model_versions').select('*').eq('kind', 'lgbm').order('created_at', { ascending: false }),
		sb.from('train_runs').select('*').order('created_at', { ascending: false }).limit(8),
		api(locals, '/train/config')
	]);
	return {
		models: (models ?? []) as ModelVersion[],
		runs: (runs ?? []) as TrainRun[],
		config: config.ok
			? (config.body as { runner: 'local' | 'vultr'; object_storage: boolean; plan: string; region: string })
			: null
	};
};

const ALL = FEATURE_GROUPS.flatMap(([, f]) => f);
const num = (v: FormDataEntryValue | null) => (v === null || v === '' ? null : Number(v));

export const actions: Actions = {
	train: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, '/train', {
			method: 'POST',
			body: JSON.stringify({
				features: ALL.filter((name) => f.get(`f_${name}`) === 'on'),
				learning_rate: num(f.get('learning_rate')),
				num_leaves: num(f.get('num_leaves')),
				scale_pos_weight: num(f.get('scale_pos_weight')),
				trials: num(f.get('trials')) ?? 0,
				use_analyst_labels: f.get('use_analyst_labels') === 'on'
			})
		});
		if (!r.ok) {
			// FastAPI validation errors arrive as a list of {loc, msg}
			const d = r.body.detail;
			const message = typeof d === 'string' ? d : Array.isArray(d) ? d.map((e) => `${e.loc?.at(-1)}: ${e.msg}`).join('; ') : 'Could not start training';
			return fail(r.status, { message });
		}
		return { message: 'Training started — follow the live log.' };
	},
	shadow: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/models/${f.get('id')}/stage`, {
			method: 'POST',
			body: JSON.stringify({ stage: f.get('stage') })
		});
		if (!r.ok) return fail(r.status, { message: r.body.detail ?? 'Could not change stage' });
		return { message: f.get('stage') === 'shadow' ? 'Shadow mode on: the scorer now also scores with this model.' : 'Shadow mode off.' };
	},
	promote: async ({ locals, request }) => {
		const f = await request.formData();
		const r = await api(locals, `/models/${f.get('id')}/promote`, {
			method: 'POST',
			body: JSON.stringify({ alert_threshold: num(f.get('alert_threshold')) })
		});
		if (!r.ok) return fail(r.status, { message: r.body.detail ?? 'Promote failed' });
		return { message: 'Promoted. The scorer switches to it within seconds.' };
	},
	rollback: async ({ locals }) => {
		const r = await api(locals, '/models/rollback', { method: 'POST' });
		if (!r.ok) return fail(r.status, { message: r.body.detail ?? 'Rollback failed' });
		return { message: 'Rolled back to the previous champion.' };
	}
};
