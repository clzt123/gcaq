import { createApp } from 'vue';
import { createPinia } from 'pinia';
import 'vant/lib/index.css';
import App from './App.vue';
import router from './router';
import { setupOfflineSync } from './offline/sync';

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount('#app');

setupOfflineSync();
