<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps<{
  xData: string[];
  yData: number[];
  color?: string;
  height?: string;
}>();

const chartRef = ref<HTMLDivElement>();
let chart: echarts.ECharts | null = null;

function initChart() {
  if (!chartRef.value) return;
  chart = echarts.init(chartRef.value);
  chart.setOption({
    grid: { top: 10, right: 10, bottom: 20, left: 40 },
    xAxis: { type: 'category', data: props.xData, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e', fontSize: 11 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#21262d' } }, axisLabel: { color: '#8b949e', fontSize: 11 } },
    series: [{
      type: 'bar', data: props.yData,
      itemStyle: { color: props.color ?? '#FF6B35', borderRadius: [4, 4, 0, 0] },
      barWidth: '60%',
    }],
  });
}

onMounted(initChart);
watch(() => [props.xData, props.yData], initChart);
</script>

<template>
  <div ref="chartRef" :style="{ height: height ?? '200px', width: '100%' }"></div>
</template>
