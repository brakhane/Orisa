import Vue from 'vue'
import Router from 'vue-router'
import Config from './views/Config.vue'

Vue.use(Router)

export default new Router({
  mode: 'history',
  base: process.env.BASE_URL,
  routes: [
    {
      path: '/config/:token',
      component: Config,
      props: true
      // component: () => import(/* webpackChunkName: "config" */ './views/Config.vue')
    }
  ]
})
