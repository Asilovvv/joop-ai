import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// What the AI did lately, for the home screen; null until loaded. A failed check keeps what is shown.
class AiResultsCubit extends Cubit<AiResults?> {
  AiResultsCubit(this._repository) : super(null);

  final JoopRepository _repository;

  Future<void> load() async {
    try {
      emit(await _repository.aiResults());
    } on ApiException {
      // keep the figures already on screen
    }
  }
}
