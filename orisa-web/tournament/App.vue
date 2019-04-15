<template>
<body>
  <div class="columns">
    <section class="column is-narrow section is-hidden-mobile">
      <aside class="menu">
        <p class="menu-label">
          General
        </p>
        <ul class="menu-list">
          <li v-for="route in routes" :key="route.path">
            <router-link :to="route.path">{{ route.meta.text }}</router-link>
          </li>
        </ul>
      </aside>
    </section>
    <section class="column section">
      <router-view></router-view>
    </section>
  </div>
</body>
</template>

<script>

import router from './router'

export default {
  name: 'app',
  components: {
  },
  data () {
    return {
      routes: router.options.routes
    }
  }
}
</script>
