<template>
  <b-form-select :state="state" :value="ch" @change="$emit('change', $event)">
    <template v-for="chan in channels">
      <option :key="chan.id" :value="chan.id" v-if="chan.type == 0">{{ chan.name }}</option>
      <optgroup :key="chan.id" :label="chan.name" v-if="chan.type == 4">
        <option :key="child.id" :value="child.id" v-for="child in chan.children">{{ child.name }}</option>
      </optgroup>
    </template>
  </b-form-select>
</template>

<script>
export default {
  name: 'channel-selector',
  data () {
    return {

    }
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
