<template>
<body>
  <nav>Nav hier</nav>
  <section class="section">
    <router-view></router-view>
  </section>
</body>
</template>

<script>
import Footer from '@/ttt/components/Footer'

export default {
  name: 'app',
  components: {
    Footer
  }
}
</script>
