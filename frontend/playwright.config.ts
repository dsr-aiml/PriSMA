import { defineConfig, devices } from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:45000,use:{baseURL:process.env.BASE_URL||'http://localhost:3000',trace:'retain-on-failure'},projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}]});
