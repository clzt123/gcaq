<script setup lang="ts">
import { useAuthStore } from '@safeguard/shared';

const authStore = useAuthStore();
</script>

<template>
  <router-view />
</template>
