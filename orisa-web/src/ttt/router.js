/*
Orisa, a simple Discord bot with good intentions
Copyright (C) 2018, 2019 Dennis Brakhane

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, version 3 only

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import Vue from 'vue'
import Router from 'vue-router'

const Test = () => import('@/ttt/views/Test')

Vue.use(Router)

export default new Router({
//  mode: 'history',
  base: `${process.env.BASE_URL}/test.html`,
  routes: [
    {
      path: '/',
      component: Test
    }
  ]
})
