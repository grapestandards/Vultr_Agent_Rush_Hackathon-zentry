// Logs in as the analyst demo user and waits for one INSERT on public.alerts via Supabase Realtime.
// Prints SUBSCRIBED when ready, then RECEIVED <id> and exits 0; exits 1 on timeout.
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.PUBLIC_SUPABASE_ANON_KEY);
const { data, error } = await supabase.auth.signInWithPassword({
	email: 'analyst@demo.zentry.local',
	password: process.env.DEMO_PASSWORD
});
if (error) {
	console.error(error.message);
	process.exit(1);
}
supabase.realtime.setAuth(data.session.access_token);
setTimeout(() => {
	console.log('TIMEOUT');
	process.exit(1);
}, 20000);
supabase
	.channel('check')
	.on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'alerts' }, (p) => {
		console.log('RECEIVED', p.new.id);
		process.exit(0);
	})
	.subscribe((status) => console.log(status));
