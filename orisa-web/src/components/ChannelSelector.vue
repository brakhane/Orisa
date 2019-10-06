<!--
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
-->
<template>
  <b-select :type="type" :value="ch" @change="$emit('change', $event)" expanded>
      <template v-for="chan in channels">
        <option :key="chan.id" :value="chan.id" v-if="chan.type == 0">{{ chan.name }}</option>
        <optgroup :key="chan.id" :label="chan.name" v-if="chan.type == 4">
          <option :key="child.id" :value="child.id" v-for="child in chan.children">{{ child.name }}</option>
        </optgroup>
      </template>
  </b-select>
</template>

<script>
export default {
  name: 'channel-selector',
  data () {
    return {}
  },
  computed: {
    ch () {
      return this.value
    }
  },
  model: {
    event: 'change'
  },
  props: ['value', 'channels', 'state']
}
</script>
