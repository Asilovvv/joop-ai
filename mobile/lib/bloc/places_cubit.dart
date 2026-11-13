import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/customer_repository.dart';
import '../data/models.dart';

class PlacesState extends Equatable {
  const PlacesState({this.places = const [], this.adding = false, this.error, this.opened});

  final List<SavedPlace> places;
  final bool adding;
  final String? error;

  /// The business just found by its code: the screen opens it.
  final Place? opened;

  @override
  List<Object?> get props => [places, adding, error, opened];
}

/// The customer's businesses: opened by code or link, remembered on the device.
class PlacesCubit extends Cubit<PlacesState> {
  PlacesCubit(this._repository) : super(const PlacesState());

  final CustomerRepository _repository;

  Future<void> load() async => emit(PlacesState(places: await _repository.savedPlaces()));

  Future<void> open(String input) async {
    final code = codeFrom(input);
    if (code == null) {
      emit(PlacesState(places: state.places, error: 'Введите код компании, например aktish, или ссылку на её чат.'));
      return;
    }
    emit(PlacesState(places: state.places, adding: true));
    try {
      final place = await _repository.place(code);
      final places = [SavedPlace(place.slug, place.name), ...state.places.where((p) => p.slug != place.slug)];
      await _repository.savePlaces(places);
      emit(PlacesState(places: places, opened: place));
    } on ApiException catch (e) {
      emit(PlacesState(places: state.places, error: e.message));
    }
  }

  Future<void> remove(String slug) async {
    final places = state.places.where((p) => p.slug != slug).toList();
    await _repository.savePlaces(places);
    emit(PlacesState(places: places));
  }
}
